"""SolubleMPNN adapter for the Paper Crane tool integration layer.

Mirrors the TypeScript `ToolAdapter` contract in
`packages/tools-sdk/src/types.ts` and the stub in
`docs/plans/02-tool-integration.md` sec. 4. Mechanically identical to
`tools/proteinmpnn/adapter.py`: SolubleMPNN *is* ProteinMPNN loaded with the
`soluble_v_48_020.pt` checkpoint. The adapter forces that checkpoint via
`--model_name`, applies a solubility-tuned default `omit_aas`, and exposes a
`solubility_strictness` enum that clamps temperature + omit list in strict
mode.

Wire format:
  IN  /inputs/request.json  (SolubleMPNN request, schemas/input.json)
      /inputs/backbones/*.pdb
  OUT /outputs/designs/*.fasta + *.json per-design metrics
      /outputs/result.json    (DesignResult, schemas/output.json)
"""
from __future__ import annotations

# TODO: replace with import from papercrane_sdk once Python SDK is published
# (see tools-sdk TypeScript package for the contract spec).
# from papercrane_sdk import Adapter, DesignRequest, DesignResult
import argparse
import dataclasses
import json
import pathlib
import re
import subprocess
from typing import Any, Dict, List, Optional


# ------------------------- Inline SDK stubs ------------------------- #

# The SolubleMPNN-biased checkpoint. Ships inside the ProteinMPNN repo under
# `soluble_model_weights/`. Kept as a module-level constant so the adapter,
# manifest tests, and the integration-mode entrypoint all reference the same
# string.
SOLUBLE_MODEL_NAME = "soluble_v_48_020.pt"
DEFAULT_OMIT_AAS = "CXHKR"
STRICT_MAX_TEMPERATURE = 0.1


@dataclasses.dataclass
class SolubleMPNNParams:
    temperature: float = 0.1
    omit_aas: str = DEFAULT_OMIT_AAS
    num_seq_per_target: int = 1
    solubility_strictness: str = "default"
    fixed_positions: Optional[Dict[str, List[int]]] = None


@dataclasses.dataclass
class DesignRequest:
    backbones: List[str]
    seeds: List[int]
    params: SolubleMPNNParams

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "DesignRequest":
        p = data.get("params") or {}
        params = SolubleMPNNParams(
            temperature=float(p.get("temperature", 0.1)),
            omit_aas=str(p.get("omit_aas", DEFAULT_OMIT_AAS)),
            num_seq_per_target=int(p.get("num_seq_per_target", 1)),
            solubility_strictness=str(p.get("solubility_strictness", "default")),
            fixed_positions=p.get("fixed_positions"),
        )
        return cls(
            backbones=list(data["backbones"]),
            seeds=list(data["seeds"]),
            params=params,
        )


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


# ------------------------- SolubleMPNN adapter ------------------------- #

ADAPTER_VERSION = "a1"

# ProteinMPNN / SolubleMPNN share the FASTA header kv format:
#   >T0_0, score=1.234, ..., seq_recovery=0.42
_FASTA_HEADER_KV = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([-0-9.eE+]+)")


class SolubleMPNNAdapter(Adapter):
    manifest_path = "tools/solublempnn/manifest.json"

    def validate(self, req: DesignRequest) -> List[Dict[str, str]]:
        errors: List[Dict[str, str]] = []
        if not req.seeds:
            errors.append({"field": "seeds", "message": "at least one seed required"})
        if not req.backbones:
            errors.append({"field": "backbones", "message": "at least one backbone required"})
        p = req.params
        if not (0 < p.temperature <= 1.0):
            errors.append({"field": "params.temperature", "message": "must be in (0, 1]"})
        if p.num_seq_per_target <= 0:
            errors.append({"field": "params.num_seq_per_target", "message": "must be > 0"})
        if p.omit_aas and not re.fullmatch(r"[ACDEFGHIKLMNPQRSTVWXY]*", p.omit_aas):
            errors.append({"field": "params.omit_aas", "message": "must contain only single-letter AA codes"})
        if p.solubility_strictness not in {"default", "strict"}:
            errors.append({
                "field": "params.solubility_strictness",
                "message": "must be 'default' or 'strict'",
            })
        return errors

    def prepare(self, req: DesignRequest, workdir: pathlib.Path) -> Dict[str, Any]:
        """Stage backbones and build the SolubleMPNN CLI invocation.

        In strict mode we re-enforce the charged-residue omit list and cap
        temperature — users can relax either knob in default mode, but strict
        mode exists specifically for campaigns that bias hard toward E. coli
        soluble expression.
        """
        workdir.mkdir(parents=True, exist_ok=True)

        pdb_dir = workdir / "pdbs"
        pdb_dir.mkdir(parents=True, exist_ok=True)

        omit_aas = req.params.omit_aas
        sampling_temp = req.params.temperature
        if req.params.solubility_strictness == "strict":
            # Union with defaults — do not *drop* a user-supplied letter, only
            # re-add ones they removed.
            omit_set = set(omit_aas) | set(DEFAULT_OMIT_AAS)
            omit_aas = "".join(sorted(omit_set))
            if sampling_temp > STRICT_MAX_TEMPERATURE:
                sampling_temp = STRICT_MAX_TEMPERATURE

        job: Dict[str, Any] = {
            "pdb_dir": str(pdb_dir),
            "out_dir": "/outputs/designs",
            "num_seq_per_target": req.params.num_seq_per_target,
            "sampling_temp": sampling_temp,
            "omit_aas": omit_aas,
            "model_name": SOLUBLE_MODEL_NAME,
            "seeds": req.seeds,
            "backbones": list(req.backbones),
            "solubility_strictness": req.params.solubility_strictness,
        }
        if req.params.fixed_positions:
            fp_path = workdir / "fixed_positions.json"
            fp_path.write_text(json.dumps(req.params.fixed_positions, indent=2))
            job["fixed_positions_jsonl"] = str(fp_path)
        return job

    def run(self, job: Dict[str, Any]) -> Dict[str, Any]:
        out_dir = pathlib.Path(job["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd: List[str] = [
            "python", "/opt/solublempnn/protein_mpnn_run.py",
            "--pdb_path", job["pdb_dir"],
            "--out_folder", str(out_dir),
            "--num_seq_per_target", str(job["num_seq_per_target"]),
            "--sampling_temp", str(job["sampling_temp"]),
            "--omit_AAs", job["omit_aas"],
            "--model_name", job["model_name"],
        ]
        if job.get("fixed_positions_jsonl"):
            cmd += ["--fixed_positions_jsonl", job["fixed_positions_jsonl"]]
        # Single seed per invocation; loop to honor the full seed list. Each
        # run appends to the same out_folder.
        for seed in job["seeds"]:
            subprocess.run(cmd + ["--seed", str(seed)], check=True)
        return {
            "out_dir": str(out_dir),
            "exit_code": 0,
            "model_name": job["model_name"],
        }

    def parse(self, raw: Dict[str, Any]) -> DesignResult:
        """Read one design record per FASTA (+ matching .json metrics)."""
        designs: List[Dict[str, Any]] = []
        out_dir = pathlib.Path(raw["out_dir"])
        for fasta in sorted(out_dir.glob("*.fasta")):
            meta_path = fasta.with_suffix(".json")
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text())
            sequence = _read_first_sequence(fasta)
            designs.append({
                "structurePath": meta.get("structurePath", ""),
                "sequence": sequence,
                "metrics": {
                    "score": float(meta.get("score", 0.0)),
                    "confidence_mean": float(meta.get("confidence_mean", 0.0)),
                },
                "seed": int(meta.get("seed", 0)),
            })
        return DesignResult(
            designs=designs,
            run_metadata={
                "tool": "solublempnn",
                "adapterVersion": ADAPTER_VERSION,
                "modelName": raw.get("model_name", SOLUBLE_MODEL_NAME),
            },
        )


def _read_first_sequence(fasta_path: pathlib.Path) -> str:
    """Return the first non-header line joined, uppercased, AA-only."""
    seq_lines: List[str] = []
    started = False
    for line in fasta_path.read_text().splitlines():
        if line.startswith(">"):
            if started:
                break
            started = True
            continue
        if started and line.strip():
            seq_lines.append(line.strip().upper())
    seq = "".join(seq_lines)
    return "".join(c for c in seq if c in "ACDEFGHIKLMNPQRSTVWY")


# ------------------------- Entrypoint ------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="SolubleMPNN Paper Crane adapter")
    parser.add_argument("--request", required=True)
    parser.add_argument("--backbones", required=True,
                        help="Directory of staged backbone PDBs (mounted by scheduler).")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    req = DesignRequest.from_json(json.loads(pathlib.Path(args.request).read_text()))
    out_root = pathlib.Path(args.output)
    out_root.mkdir(parents=True, exist_ok=True)

    adapter = SolubleMPNNAdapter()
    errors = adapter.validate(req)
    if errors:
        (out_root / "errors.json").write_text(json.dumps({"errors": errors}, indent=2))
        print(json.dumps({"errors": errors}), flush=True)
        return 2

    job = adapter.prepare(req, out_root / "workdir")
    # The scheduler has already staged backbones into args.backbones; point
    # the job at that directory rather than the workdir scratch path so the
    # upstream CLI sees the real inputs.
    job["pdb_dir"] = args.backbones
    raw = adapter.run(job)
    result = adapter.parse(raw)
    (out_root / "result.json").write_text(json.dumps(result.to_json(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
