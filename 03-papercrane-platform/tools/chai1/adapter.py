"""Chai-1 adapter for the Paper Crane tool integration layer.

Mirrors the TypeScript `ToolAdapter` contract in
`packages/tools-sdk/src/types.ts` and the stub in
`docs/plans/02-tool-integration.md` sec. 4.

Chai-1 is a structure predictor with open weights but a non-commercial license
(chaiDiscovery/chai-1 terms). The manifest sets `licenseGate: true`, which makes
the platform UI show a EULA modal before each run. See LICENSE-GATE.md.

Wire format:
  IN  /inputs/request.json   (Chai-1 request, schemas/input.json)
  OUT /outputs/predictions/<seed>/pred.model_idx_<N>.cif
      /outputs/predictions/<seed>/metrics.model_idx_<N>.json
      /outputs/result.json   (normalized result, schemas/output.json)
"""
from __future__ import annotations

# TODO: replace with import from papercrane_sdk once Python SDK is published
# (see tools-sdk TypeScript package for the contract spec).
# from papercrane_sdk import Adapter, StructureRequest, StructureResult
import argparse
import dataclasses
import json
import pathlib
import subprocess
from typing import Any, Dict, List, Optional


# ------------------------- Inline SDK stubs ------------------------- #

@dataclasses.dataclass
class Chain:
    id: str
    sequence: str


@dataclasses.dataclass
class Chai1Params:
    num_trunk_recycles: Optional[int] = None
    num_diffn_timesteps: Optional[int] = None
    use_esm_embeddings: Optional[bool] = None


@dataclasses.dataclass
class StructureRequest:
    chains: List[Chain]
    seeds: List[int]
    params: Optional[Chai1Params] = None
    binder_chain_id: Optional[str] = None

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "StructureRequest":
        chains = [Chain(**c) for c in data["chains"]]
        p = data.get("params") or {}
        params = Chai1Params(
            num_trunk_recycles=p.get("num_trunk_recycles"),
            num_diffn_timesteps=p.get("num_diffn_timesteps"),
            use_esm_embeddings=p.get("use_esm_embeddings"),
        ) if p else None
        return cls(
            chains=chains,
            seeds=list(data.get("seeds") or [42]),
            params=params,
            binder_chain_id=data.get("binderChainId"),
        )


@dataclasses.dataclass
class StructureResult:
    predictions: List[Dict[str, Any]]
    run_metadata: Dict[str, Any]

    def to_json(self) -> Dict[str, Any]:
        return {"predictions": self.predictions, "runMetadata": self.run_metadata}


class Adapter:
    """Stub base; mirrors `ToolAdapter` in the TS SDK."""
    manifest_path: str = ""

    def validate(self, req: StructureRequest) -> List[Dict[str, str]]: return []
    def prepare(self, req, workdir): raise NotImplementedError
    def run(self, job): raise NotImplementedError
    def parse(self, raw): raise NotImplementedError


# ------------------------- Chai-1 adapter ------------------------- #

ADAPTER_VERSION = "a1"
DEFAULT_NUM_TRUNK_RECYCLES = 3
DEFAULT_NUM_DIFFN_TIMESTEPS = 200


class Chai1Adapter(Adapter):
    manifest_path = "tools/chai1/manifest.json"

    def validate(self, req: StructureRequest) -> List[Dict[str, str]]:
        errors: List[Dict[str, str]] = []
        if not req.chains:
            errors.append({"field": "chains", "message": "at least one chain required"})
        ids = [c.id for c in req.chains]
        if len(set(ids)) != len(ids):
            errors.append({"field": "chains", "message": "chain ids must be unique"})
        for i, c in enumerate(req.chains):
            if len(c.sequence) == 0:
                errors.append({
                    "field": f"chains[{i}].sequence",
                    "message": "sequence must be non-empty",
                })
        if not req.seeds:
            errors.append({"field": "seeds", "message": "at least one seed required"})
        if req.binder_chain_id and req.binder_chain_id not in ids:
            errors.append({
                "field": "binderChainId",
                "message": f"binder chain '{req.binder_chain_id}' not in chains",
            })
        if req.params:
            if req.params.num_trunk_recycles is not None and not (
                1 <= req.params.num_trunk_recycles <= 10
            ):
                errors.append({
                    "field": "params.num_trunk_recycles",
                    "message": "must be in [1, 10]",
                })
            if req.params.num_diffn_timesteps is not None and not (
                10 <= req.params.num_diffn_timesteps <= 500
            ):
                errors.append({
                    "field": "params.num_diffn_timesteps",
                    "message": "must be in [10, 500]",
                })
        return errors

    def _write_fasta(self, chains: List[Chain], path: pathlib.Path) -> None:
        lines: List[str] = []
        for c in chains:
            # Chai-1 FASTA header convention: `>protein|name=<id>`.
            lines.append(f">protein|name={c.id}")
            lines.append(c.sequence)
        path.write_text("\n".join(lines) + "\n")

    def prepare(self, req: StructureRequest, workdir: pathlib.Path) -> Dict[str, Any]:
        workdir.mkdir(parents=True, exist_ok=True)
        fasta_path = workdir / "input.fasta"
        self._write_fasta(req.chains, fasta_path)

        params = req.params or Chai1Params()
        cfg: Dict[str, Any] = {
            "fasta_path": str(fasta_path),
            "seeds": req.seeds,
            "num_trunk_recycles": params.num_trunk_recycles or DEFAULT_NUM_TRUNK_RECYCLES,
            "num_diffn_timesteps": params.num_diffn_timesteps or DEFAULT_NUM_DIFFN_TIMESTEPS,
            "use_esm_embeddings": bool(params.use_esm_embeddings),
            "binder_chain_id": req.binder_chain_id,
        }
        cfg_path = workdir / "chai1.json"
        cfg_path.write_text(json.dumps(cfg, indent=2))
        return {
            "cfg": str(cfg_path),
            "fasta": str(fasta_path),
            "out_dir": "/outputs/predictions",
            "seeds": req.seeds,
            "binder_chain_id": req.binder_chain_id,
            "num_trunk_recycles": cfg["num_trunk_recycles"],
            "num_diffn_timesteps": cfg["num_diffn_timesteps"],
        }

    def run(self, job: Dict[str, Any]) -> Dict[str, Any]:
        out_root = pathlib.Path(job["out_dir"])
        out_root.mkdir(parents=True, exist_ok=True)
        seed_dirs: List[str] = []
        for seed in job["seeds"]:
            seed_dir = out_root / f"seed_{seed}"
            seed_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "python", "-m", "chai_lab.main", "fold",
                    "--fasta-file", job["fasta"],
                    "--output-dir", str(seed_dir),
                    "--seed", str(seed),
                    "--num-trunk-recycles", str(job["num_trunk_recycles"]),
                    "--num-diffn-timesteps", str(job["num_diffn_timesteps"]),
                ],
                check=True,
            )
            seed_dirs.append(str(seed_dir))
        return {
            "out_dir": str(out_root),
            "seed_dirs": seed_dirs,
            "binder_chain_id": job.get("binder_chain_id"),
            "exit_code": 0,
        }

    def _metric_for_cif(self, cif_path: pathlib.Path) -> Optional[Dict[str, Any]]:
        """Return Chai-1 metrics JSON paired with a CIF, or None if missing.

        Chai-1 emits `pred.model_idx_<N>.cif` alongside a metrics JSON. We accept
        either `pred.model_idx_<N>.json` (paired) or `metrics.model_idx_<N>.json`.
        """
        stem = cif_path.stem  # e.g. "pred.model_idx_0"
        candidates = [
            cif_path.with_suffix(".json"),
            cif_path.parent / f"metrics.{stem.split('.', 1)[1]}.json"
            if "." in stem else cif_path.with_suffix(".json"),
        ]
        for cand in candidates:
            if cand.exists():
                return json.loads(cand.read_text())
        return None

    @staticmethod
    def _aggregate(metrics: Dict[str, Any]) -> float:
        """Composite quality score — weighted sum of iptm, ptm, plddt_mean.

        Kept deliberately simple; the canonical validator recomputes ipSAE/DockQ
        downstream. Weights mirror the Chai-1 README's recommendation (iptm-heavy
        for interface quality).
        """
        iptm = float(metrics.get("iptm", 0.0))
        ptm = float(metrics.get("ptm", 0.0))
        plddt_mean = float(metrics.get("plddt_mean", 0.0))
        return 0.6 * iptm + 0.2 * ptm + 0.2 * (plddt_mean / 100.0)

    def parse(self, raw: Dict[str, Any]) -> StructureResult:
        predictions: List[Dict[str, Any]] = []
        out_root = pathlib.Path(raw["out_dir"])
        for seed_dir in sorted(out_root.glob("seed_*")):
            try:
                seed = int(seed_dir.name.split("_", 1)[1])
            except (IndexError, ValueError):
                continue
            for cif in sorted(seed_dir.glob("pred.model_idx_*.cif")):
                meta = self._metric_for_cif(cif)
                if meta is None:
                    continue
                # Parse model_idx from filename suffix.
                try:
                    model_idx = int(cif.stem.rsplit("_", 1)[1])
                except (IndexError, ValueError):
                    model_idx = int(meta.get("model_idx", 0))

                metrics = {
                    "plddt_mean": float(meta.get("plddt_mean", meta.get("plddt", 0.0))),
                    "plddt_binder": float(meta.get("plddt_binder", 0.0)),
                    "ptm": float(meta.get("ptm", 0.0)),
                    "iptm": float(meta.get("iptm", 0.0)),
                }
                metrics["aggregate_score"] = self._aggregate(metrics)

                entry: Dict[str, Any] = {
                    "structurePath": str(cif),
                    "seed": seed,
                    "model_idx": model_idx,
                    "metrics": metrics,
                }
                pae = cif.with_name(cif.stem + ".pae.npy")
                if pae.exists():
                    entry["paePath"] = str(pae)
                predictions.append(entry)
        return StructureResult(
            predictions=predictions,
            run_metadata={
                "tool": "chai1",
                "adapterVersion": ADAPTER_VERSION,
                "licenseAcknowledged": True,
            },
        )


# ------------------------- Entrypoint ------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="Chai-1 Paper Crane adapter")
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    req = StructureRequest.from_json(json.loads(pathlib.Path(args.request).read_text()))
    out_root = pathlib.Path(args.output)
    out_root.mkdir(parents=True, exist_ok=True)

    adapter = Chai1Adapter()
    errors = adapter.validate(req)
    if errors:
        (out_root / "errors.json").write_text(json.dumps({"errors": errors}, indent=2))
        print(json.dumps({"errors": errors}), flush=True)
        return 2

    job = adapter.prepare(req, out_root / "workdir")
    raw = adapter.run(job)
    result = adapter.parse(raw)
    (out_root / "result.json").write_text(json.dumps(result.to_json(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
