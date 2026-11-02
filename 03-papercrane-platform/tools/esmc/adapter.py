"""ESM-C 300M adapter for the Paper Crane tool integration layer.

Unlike the design tools (BindCraft, ProteinMPNN, RFdiffusion, BoltzGen) this
adapter wraps an *embedding / scoring* model. The same `ToolAdapter` contract
is implemented — `validate` / `prepare` / `run` / `parse` — but the inputs are
sequences (not backbones, not targets) and the outputs are either:

  - mode="score": per-sequence pseudo-log-likelihood metrics used to filter
    implausible designs before structure prediction.
  - mode="embed": per-residue or pooled hidden states persisted as `.npy`
    files and referenced from `result.json` via `embedding_path`.

ESM-C is EvolutionaryScale's successor to ESM-2 — a newer, stronger protein
language model with the same kinds of outputs (embeddings + pLL). The 300M tier
ships under the commercial-clean Cambrian Open License.

Wire format:
  IN  /inputs/request.json  (ESM-C request, schemas/input.json)
  OUT /outputs/seqs.fasta                     (staged by prepare)
      /outputs/scores.json   (mode=score)     (emitted by runner)
      /outputs/embeddings.json (mode=embed)   (emitted by runner)
      /outputs/<id>.npy      (mode=embed, one per sequence)
      /outputs/result.json   (normalized DesignResult, schemas/output.json)
"""
from __future__ import annotations

# TODO: replace with import from papercrane_sdk once Python SDK is published
# (see tools-sdk TypeScript package for the contract spec).
# from papercrane_sdk import Adapter, DesignRequest, DesignResult
import argparse
import dataclasses
import json
import math
import pathlib
import re
import subprocess
from typing import Any, Dict, List, Optional


# ------------------------- Inline SDK stubs ------------------------- #

_VALID_MODES = {"score", "embed"}
_VALID_POOLS = {"mean", "cls", "none"}


@dataclasses.dataclass
class ESMCParams:
    mode: str = "score"
    pool: str = "mean"
    layer: int = 30


@dataclasses.dataclass
class SequenceRecord:
    id: str
    sequence: str


@dataclasses.dataclass
class DesignRequest:
    sequences: List[SequenceRecord]
    seeds: List[int]
    params: ESMCParams

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "DesignRequest":
        p = data.get("params") or {}
        params = ESMCParams(
            mode=str(p.get("mode", "score")),
            pool=str(p.get("pool", "mean")),
            layer=int(p.get("layer", 30)),
        )
        seqs = [
            SequenceRecord(id=str(s["id"]), sequence=str(s["sequence"]).upper())
            for s in data["sequences"]
        ]
        seeds = list(data.get("seeds") or [0])
        return cls(sequences=seqs, seeds=seeds, params=params)


@dataclasses.dataclass
class DesignResult:
    designs: List[Dict[str, Any]]
    run_metadata: Dict[str, Any]

    def to_json(self) -> Dict[str, Any]:
        return {"designs": self.designs, "runMetadata": self.run_metadata}


class Adapter:
    """Stub base; mirrors `ToolAdapter` in the TS SDK."""
    manifest_path: str = ""

    def validate(self, req: DesignRequest) -> List[Dict[str, str]]: return []
    def prepare(self, req, workdir): raise NotImplementedError
    def run(self, job): raise NotImplementedError
    def parse(self, raw): raise NotImplementedError


# ------------------------- ESM-C adapter ------------------------- #

ADAPTER_VERSION = "a1"
MODEL_NAME = "esmc_300m"
EMBEDDING_DIM = 960  # fixed for 300M

_AA_RE = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")


class ESMCAdapter(Adapter):
    manifest_path = "tools/esmc/manifest.json"

    def validate(self, req: DesignRequest) -> List[Dict[str, str]]:
        errors: List[Dict[str, str]] = []
        if not req.sequences:
            errors.append({"field": "sequences", "message": "at least one sequence required"})
        if not req.seeds:
            errors.append({"field": "seeds", "message": "at least one seed required"})
        for i, s in enumerate(req.sequences):
            if not s.id:
                errors.append({"field": f"sequences[{i}].id", "message": "id must be non-empty"})
            if not s.sequence or not _AA_RE.match(s.sequence):
                errors.append({
                    "field": f"sequences[{i}].sequence",
                    "message": "must be non-empty and contain only canonical AAs",
                })
        p = req.params
        if p.mode not in _VALID_MODES:
            errors.append({"field": "params.mode", "message": f"must be one of {sorted(_VALID_MODES)}"})
        if p.pool not in _VALID_POOLS:
            errors.append({"field": "params.pool", "message": f"must be one of {sorted(_VALID_POOLS)}"})
        if not (0 <= p.layer <= 30):
            errors.append({"field": "params.layer", "message": "must be in [0, 30] for esmc_300m"})
        return errors

    def prepare(self, req: DesignRequest, workdir: pathlib.Path) -> Dict[str, Any]:
        """Write the FASTA the runner consumes and capture CLI args."""
        workdir.mkdir(parents=True, exist_ok=True)
        fasta_path = workdir / "seqs.fasta"
        with fasta_path.open("w") as fh:
            for s in req.sequences:
                fh.write(f">{s.id}\n{s.sequence}\n")

        job: Dict[str, Any] = {
            "fasta_path": str(fasta_path),
            "out_dir": "/outputs",
            "mode": req.params.mode,
            "pool": req.params.pool,
            "layer": req.params.layer,
            "seeds": list(req.seeds),
            "sequences": [{"id": s.id, "sequence": s.sequence} for s in req.sequences],
        }
        return job

    def run(self, job: Dict[str, Any]) -> Dict[str, Any]:
        out_dir = pathlib.Path(job["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd: List[str] = [
            "python", "-m", "papercrane.esmc_runner",
            "--fasta", job["fasta_path"],
            "--mode", job["mode"],
            "--out", str(out_dir),
        ]
        if job["mode"] == "embed":
            cmd += ["--pool", job["pool"], "--layer", str(job["layer"])]
        subprocess.run(cmd, check=True)
        return {"out_dir": str(out_dir), "mode": job["mode"], "job": job}

    def parse(self, raw: Dict[str, Any]) -> DesignResult:
        out_dir = pathlib.Path(raw["out_dir"])
        mode = raw["mode"]
        job = raw.get("job", {})
        seed = int((job.get("seeds") or [0])[0])
        seq_lookup = {s["id"]: s["sequence"] for s in job.get("sequences", [])}

        designs: List[Dict[str, Any]] = []

        if mode == "score":
            scores = json.loads((out_dir / "scores.json").read_text())
            # Runner emits: [{"id": ..., "pll_mean": ..., "pll_sum": ..., "pll_min": ...}, ...]
            for rec in scores:
                pll_mean = float(rec["pll_mean"])
                metrics = {
                    "pll_mean": pll_mean,
                    "pll_sum": float(rec["pll_sum"]),
                    "pll_min": float(rec["pll_min"]),
                    "ppl": float(rec.get("ppl", math.exp(-pll_mean))),
                }
                design: Dict[str, Any] = {
                    "id": str(rec["id"]),
                    "seed": int(rec.get("seed", seed)),
                    "mode": "score",
                    "metrics": metrics,
                }
                if rec["id"] in seq_lookup:
                    design["sequence"] = seq_lookup[rec["id"]]
                designs.append(design)

        elif mode == "embed":
            emb = json.loads((out_dir / "embeddings.json").read_text())
            # Runner emits: [{"id": ..., "path": "<id>.npy", "shape": [L, 960], "layer": 30, "pool": "mean"}, ...]
            for rec in emb:
                design = {
                    "id": str(rec["id"]),
                    "seed": int(rec.get("seed", seed)),
                    "mode": "embed",
                    "embedding_path": str(rec["path"]),
                    "shape": [int(x) for x in rec["shape"]],
                    "layer": int(rec.get("layer", job.get("layer", 30))),
                    "pool": str(rec.get("pool", job.get("pool", "mean"))),
                }
                if rec["id"] in seq_lookup:
                    design["sequence"] = seq_lookup[rec["id"]]
                designs.append(design)
        else:
            raise ValueError(f"unknown mode: {mode!r}")

        return DesignResult(
            designs=designs,
            run_metadata={
                "tool": "esmc",
                "adapterVersion": ADAPTER_VERSION,
                "mode": mode,
                "model": MODEL_NAME,
            },
        )


# ------------------------- Entrypoint ------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="ESM-C 300M Paper Crane adapter")
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    req = DesignRequest.from_json(json.loads(pathlib.Path(args.request).read_text()))
    out_root = pathlib.Path(args.output)
    out_root.mkdir(parents=True, exist_ok=True)

    adapter = ESMCAdapter()
    errors = adapter.validate(req)
    if errors:
        (out_root / "errors.json").write_text(json.dumps({"errors": errors}, indent=2))
        print(json.dumps({"errors": errors}), flush=True)
        return 2

    job = adapter.prepare(req, out_root / "workdir")
    # The runner writes into /outputs directly; route its artefacts there
    # rather than the scratch workdir so the scheduler's rsync sees them.
    job["out_dir"] = str(out_root)
    raw = adapter.run(job)
    result = adapter.parse(raw)
    (out_root / "result.json").write_text(json.dumps(result.to_json(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
