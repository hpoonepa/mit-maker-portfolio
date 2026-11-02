"""Boltz-1 adapter for the Paper Crane tool integration layer.

Mirrors the TypeScript `ToolAdapter` contract in
`packages/tools-sdk/src/types.ts` and the stub in
`docs/plans/02-tool-integration.md` sec. 4 / catalog §8.

Role: Boltz-1 is the older / lighter sibling of Boltz-2 (same upstream repo,
different model checkpoint). It is used primarily as a STRUCTURE PREDICTOR /
BINDER VALIDATOR. The request carries a target sequence + one or more binder
sequences to co-fold; an optional target PDB is passed through as a structural
template. Wire format is identical to Boltz-2 (CIF + metrics JSON).

Wire format:
  IN  /inputs/request.json  (Boltz1Request, schemas/input.json)
      /inputs/target.pdb    (optional, used as template)
  OUT /outputs/predictions/<seed>/prediction_<NNNN>.cif + *.json per prediction
      /outputs/result.json  (Boltz1Result, schemas/output.json)
"""
from __future__ import annotations

# TODO: replace with import from papercrane_sdk once Python SDK is published
# (see tools-sdk TypeScript package for the contract spec).
# from papercrane_sdk import Adapter
import argparse
import dataclasses
import json
import pathlib
import subprocess
from typing import Any, Dict, List, Optional


# ------------------------- Inline SDK stubs ------------------------- #

@dataclasses.dataclass
class BinderSpec:
    sequence: str
    seed: int


@dataclasses.dataclass
class Boltz1Params:
    recycling_steps: int = 3
    sampling_steps: int = 200
    diffusion_samples: int = 3


@dataclasses.dataclass
class Boltz1Request:
    target_seq: str
    binders: List[BinderSpec]
    target_pdb: Optional[str] = None
    params: Boltz1Params = dataclasses.field(default_factory=Boltz1Params)

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "Boltz1Request":
        binders = [BinderSpec(sequence=b["sequence"], seed=int(b["seed"]))
                   for b in data["binders"]]
        p = data.get("params") or {}
        params = Boltz1Params(
            recycling_steps=int(p.get("recycling_steps", 3)),
            sampling_steps=int(p.get("sampling_steps", 200)),
            diffusion_samples=int(p.get("diffusion_samples", 3)),
        )
        return cls(
            target_seq=data["targetSeq"],
            binders=binders,
            target_pdb=data.get("targetPdb"),
            params=params,
        )


@dataclasses.dataclass
class Boltz1Result:
    predictions: List[Dict[str, Any]]
    run_metadata: Dict[str, Any]

    def to_json(self) -> Dict[str, Any]:
        return {"predictions": self.predictions, "runMetadata": self.run_metadata}


class Adapter:
    """Stub base; mirrors `ToolAdapter` in the TS SDK."""
    manifest_path: str = ""

    def validate(self, req: Boltz1Request) -> List[Dict[str, str]]: return []
    def prepare(self, req, workdir): raise NotImplementedError
    def run(self, job): raise NotImplementedError
    def parse(self, raw): raise NotImplementedError


# ------------------------- YAML emit ------------------------- #
#
# Boltz-1's CLI consumes the same YAML doc format as Boltz-2. We hand-roll the
# writer (no PyYAML dep in the production image) so this module stays
# import-light.

def _emit_boltz_yaml(
    target_seq: str,
    binder_seq: str,
    template_path: Optional[str],
) -> str:
    lines = [
        "version: 1",
        "sequences:",
        "  - protein:",
        "      id: A",
        f"      sequence: {target_seq}",
        "  - protein:",
        "      id: B",
        f"      sequence: {binder_seq}",
    ]
    if template_path:
        lines += [
            "templates:",
            f"  - cif_url: {template_path}",
        ]
    return "\n".join(lines) + "\n"


# ------------------------- Boltz-1 adapter ------------------------- #

ADAPTER_VERSION = "a1"


class Boltz1Adapter(Adapter):
    manifest_path = "tools/boltz1/manifest.json"

    def validate(self, req: Boltz1Request) -> List[Dict[str, str]]:
        errors: List[Dict[str, str]] = []
        if not req.target_seq:
            errors.append({"field": "targetSeq", "message": "required"})
        if not req.binders:
            errors.append({"field": "binders", "message": "at least one binder required"})
        seen_seeds = set()
        for i, b in enumerate(req.binders):
            if not b.sequence:
                errors.append({"field": f"binders[{i}].sequence", "message": "required"})
            if b.seed in seen_seeds:
                errors.append({
                    "field": f"binders[{i}].seed",
                    "message": f"duplicate seed {b.seed}",
                })
            seen_seeds.add(b.seed)
        p = req.params
        if not 1 <= p.recycling_steps <= 10:
            errors.append({"field": "params.recycling_steps",
                           "message": "must be in [1, 10]"})
        if not 10 <= p.sampling_steps <= 1000:
            errors.append({"field": "params.sampling_steps",
                           "message": "must be in [10, 1000]"})
        if not 1 <= p.diffusion_samples <= 25:
            errors.append({"field": "params.diffusion_samples",
                           "message": "must be in [1, 25]"})
        return errors

    def prepare(self, req: Boltz1Request, workdir: pathlib.Path) -> Dict[str, Any]:
        workdir.mkdir(parents=True, exist_ok=True)
        jobs: List[Dict[str, Any]] = []
        for binder in req.binders:
            job_dir = workdir / f"seed_{binder.seed}"
            job_dir.mkdir(parents=True, exist_ok=True)
            yaml_text = _emit_boltz_yaml(
                target_seq=req.target_seq,
                binder_seq=binder.sequence,
                template_path=req.target_pdb,
            )
            cfg_path = job_dir / "boltz.yaml"
            cfg_path.write_text(yaml_text)
            jobs.append({
                "seed": binder.seed,
                "cfg": str(cfg_path),
                "out_dir": str(job_dir / "out"),
            })
        return {
            "jobs": jobs,
            "params": dataclasses.asdict(req.params),
            "out_root": str(workdir),
        }

    def run(self, job: Dict[str, Any]) -> Dict[str, Any]:
        params = job["params"]
        for sub in job["jobs"]:
            out_dir = pathlib.Path(sub["out_dir"])
            out_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "boltz", "predict", sub["cfg"],
                    "--out_dir", str(out_dir),
                    "--recycling_steps", str(params["recycling_steps"]),
                    "--sampling_steps", str(params["sampling_steps"]),
                    "--diffusion_samples", str(params["diffusion_samples"]),
                    "--seed", str(sub["seed"]),
                ],
                check=True,
            )
        return {"jobs": job["jobs"]}

    def parse(self, raw: Dict[str, Any]) -> Boltz1Result:
        predictions: List[Dict[str, Any]] = []
        for sub in raw["jobs"]:
            out_dir = pathlib.Path(sub["out_dir"])
            cifs = sorted(out_dir.rglob("prediction_*.cif"))
            if not cifs:
                continue
            # Boltz-1 ranks its diffusion samples; the first is the best-scored.
            top_cif = cifs[0]
            meta_path = top_cif.with_suffix(".json")
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text())
            predictions.append({
                "structurePath": str(top_cif),
                "seed": int(sub["seed"]),
                "metrics": {
                    "plddt_mean": float(meta.get("plddt_mean", 0.0)),
                    "plddt_binder": float(meta.get("plddt_binder", 0.0)),
                    "ptm": float(meta.get("ptm", 0.0)),
                    "iptm": float(meta.get("iptm", 0.0)),
                    "ipae_mean": float(meta.get("ipae_mean", 0.0)),
                    "per_chain_ptm": {
                        k: float(v) for k, v in
                        (meta.get("per_chain_ptm") or {}).items()
                    },
                },
            })
        return Boltz1Result(
            predictions=predictions,
            run_metadata={"tool": "boltz1", "adapterVersion": ADAPTER_VERSION},
        )


# ------------------------- Entrypoint ------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="Boltz-1 Paper Crane adapter")
    parser.add_argument("--request", required=True)
    parser.add_argument("--target", required=False,
                        help="Optional target PDB; used as a template.")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    data = json.loads(pathlib.Path(args.request).read_text())
    # If a target PDB is staged on disk and the request didn't override the
    # path, use the one the scheduler mounted at /inputs.
    if args.target and not data.get("targetPdb"):
        target = pathlib.Path(args.target)
        if target.exists():
            data["targetPdb"] = str(target)

    req = Boltz1Request.from_json(data)
    out_root = pathlib.Path(args.output)
    out_root.mkdir(parents=True, exist_ok=True)

    adapter = Boltz1Adapter()
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
