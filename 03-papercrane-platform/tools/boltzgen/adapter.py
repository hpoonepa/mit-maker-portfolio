"""BoltzGen adapter for the Paper Crane tool integration layer.

Mirrors the TypeScript `ToolAdapter` contract in
`packages/tools-sdk/src/types.ts` and the stub in
`docs/plans/02-tool-integration.md` sec. 4 / catalog.

Role: BoltzGen is an ALL-ATOM binder generator. Unlike BindCraft (backbone
hallucination -> MPNN sequence design -> AF2 validation), BoltzGen emits full
structures with side chains in a single diffusion pass. It is ligand-aware —
an optional SDF/PDB ligand can be supplied via `toolParams.ligand` (or as a
top-level `ligand` field in the normalized request), and the binder pocket is
co-designed around it.

Wire format:
  IN  /inputs/request.json  (DesignRequest, schemas/input.json)
      /inputs/target.pdb
      /inputs/ligand.{sdf,pdb}  (optional — referenced by request.ligand)
  OUT /outputs/designs/*.pdb   + *.json per-design metrics
      /outputs/result.json     (DesignResult, schemas/output.json)
"""
from __future__ import annotations

# TODO: replace with import from papercrane_sdk once Python SDK is published
# (see tools-sdk TypeScript package for the contract spec).
# from papercrane_sdk import Adapter, DesignRequest, DesignResult, ...
import argparse
import dataclasses
import json
import pathlib
import subprocess
from typing import Any, Dict, List, Optional


# ------------------------- Inline SDK stubs ------------------------- #

@dataclasses.dataclass
class Residue:
    chain: str
    resi: int


@dataclasses.dataclass
class DesignConstraints:
    length_range: Optional[List[int]] = None


@dataclasses.dataclass
class DesignRequest:
    target_pdb: str
    seeds: List[int]
    num_designs: int
    target_chain: Optional[str] = None
    hotspots: Optional[List[Residue]] = None
    constraints: Optional[DesignConstraints] = None
    tool_params: Optional[Dict[str, Any]] = None
    ligand: Optional[str] = None

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "DesignRequest":
        hotspots = None
        if data.get("hotspots"):
            hotspots = [Residue(chain=h["chain"], resi=int(h["resi"]))
                        for h in data["hotspots"]]
        constraints = None
        c = data.get("constraints")
        if c:
            lr = c.get("lengthRange")
            constraints = DesignConstraints(
                length_range=list(lr) if lr else None,
            )
        return cls(
            target_pdb=data["targetPdb"],
            seeds=[int(s) for s in data["seeds"]],
            num_designs=int(data["numDesigns"]),
            target_chain=data.get("targetChain"),
            hotspots=hotspots,
            constraints=constraints,
            tool_params=data.get("toolParams") or {},
            ligand=data.get("ligand"),
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


# ------------------------- YAML emit ------------------------- #
#
# BoltzGen's CLI consumes a YAML config per run. We hand-roll the writer (no
# PyYAML dep in the production image) so this module stays import-light.

def _emit_boltzgen_yaml(
    target_pdb: str,
    target_chain: str,
    hotspots: List[str],
    length_range: List[int],
    num_designs: int,
    seeds: List[int],
    diffusion_steps: int,
    temperature: float,
    ligand: Optional[str],
) -> str:
    lines = [
        "version: 1",
        f"target_pdb: {target_pdb}",
        f"target_chain: {target_chain}",
        "hotspots:",
    ]
    if hotspots:
        for h in hotspots:
            lines.append(f"  - {h}")
    else:
        lines.append("  []")
    lines += [
        f"length_range: [{length_range[0]}, {length_range[1]}]",
        f"num_designs: {num_designs}",
        "seeds:",
    ]
    for s in seeds:
        lines.append(f"  - {s}")
    lines += [
        f"diffusion_steps: {diffusion_steps}",
        f"temperature: {temperature}",
    ]
    if ligand:
        lines.append(f"ligand: {ligand}")
    return "\n".join(lines) + "\n"


# ------------------------- BoltzGen adapter ------------------------- #

ADAPTER_VERSION = "a1"


class BoltzGenAdapter(Adapter):
    manifest_path = "tools/boltzgen/manifest.json"

    def validate(self, req: DesignRequest) -> List[Dict[str, str]]:
        errors: List[Dict[str, str]] = []
        if not req.target_pdb:
            errors.append({"field": "targetPdb", "message": "required"})
        if not req.seeds:
            errors.append({"field": "seeds", "message": "at least one seed required"})
        if req.num_designs <= 0:
            errors.append({"field": "numDesigns", "message": "must be > 0"})
        if req.constraints and req.constraints.length_range:
            lo, hi = req.constraints.length_range
            if lo < 20 or hi > 300 or lo > hi:
                errors.append({
                    "field": "constraints.lengthRange",
                    "message": "invalid length range",
                })
        p = req.tool_params or {}
        if "diffusion_steps" in p and not 10 <= int(p["diffusion_steps"]) <= 1000:
            errors.append({
                "field": "toolParams.diffusion_steps",
                "message": "must be in [10, 1000]",
            })
        if "temperature" in p and not 0.0 <= float(p["temperature"]) <= 2.0:
            errors.append({
                "field": "toolParams.temperature",
                "message": "must be in [0.0, 2.0]",
            })
        return errors

    def prepare(self, req: DesignRequest, workdir: pathlib.Path) -> Dict[str, Any]:
        workdir.mkdir(parents=True, exist_ok=True)

        length_range = (
            list(req.constraints.length_range)
            if req.constraints and req.constraints.length_range
            else [60, 150]
        )
        params = req.tool_params or {}
        diffusion_steps = int(params.get("diffusion_steps", 200))
        temperature = float(params.get("temperature", 0.1))

        # Ligand can be supplied either at the top level (normalized request
        # field) or via toolParams.ligand. Top-level wins.
        ligand = req.ligand or params.get("ligand")

        hotspots = [f"{h.chain}{h.resi}" for h in (req.hotspots or [])]

        yaml_text = _emit_boltzgen_yaml(
            target_pdb=req.target_pdb or "/inputs/target.pdb",
            target_chain=req.target_chain or "A",
            hotspots=hotspots,
            length_range=length_range,
            num_designs=req.num_designs,
            seeds=req.seeds,
            diffusion_steps=diffusion_steps,
            temperature=temperature,
            ligand=ligand,
        )
        cfg_path = workdir / "config.yaml"
        cfg_path.write_text(yaml_text)

        return {
            "cfg": str(cfg_path),
            "out_dir": "/outputs/designs",
            "seeds": list(req.seeds),
            "ligand": ligand,
        }

    def run(self, job: Dict[str, Any]) -> Dict[str, Any]:
        out_dir = pathlib.Path(job["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        # BoltzGen's design.py is invoked once per seed — each call writes into
        # a seed-partitioned subdirectory under `out_dir`.
        for seed in job["seeds"]:
            subprocess.run(
                [
                    "python", "/opt/boltzgen/scripts/design.py",
                    "--config", job["cfg"],
                    "--out", str(out_dir),
                ],
                check=True,
            )
        return {"out_dir": str(out_dir), "exit_code": 0}

    def parse(self, raw: Dict[str, Any]) -> DesignResult:
        designs: List[Dict[str, Any]] = []
        out_dir = pathlib.Path(raw["out_dir"])
        for pdb in sorted(out_dir.glob("*.pdb")):
            meta_path = pdb.with_suffix(".json")
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text())
            metrics: Dict[str, float] = {
                "plddt_mean": float(meta.get("plddt_mean", 0.0)),
                "clash_score": float(meta.get("clash_score", 0.0)),
                "sidechain_confidence": float(meta.get("sidechain_confidence", 0.0)),
                "hotspot_contact": float(meta.get("hotspot_contact", 0.0)),
            }
            # Only emit ligand_rmsd when upstream reports it (ligand-aware run).
            if "ligand_rmsd" in meta:
                metrics["ligand_rmsd"] = float(meta["ligand_rmsd"])
            designs.append({
                "structurePath": str(pdb),
                "sequence": meta["sequence"],
                "metrics": metrics,
                "seed": int(meta["seed"]),
            })
        return DesignResult(
            designs=designs,
            run_metadata={"tool": "boltzgen", "adapterVersion": ADAPTER_VERSION},
        )


# ------------------------- Entrypoint ------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="BoltzGen Paper Crane adapter")
    parser.add_argument("--request", required=True)
    parser.add_argument("--target", required=False,
                        help="Target PDB staged at /inputs/target.pdb by the scheduler.")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    data = json.loads(pathlib.Path(args.request).read_text())
    # If the scheduler staged a target PDB on disk and the request didn't set
    # an explicit path, fall back to the mounted location.
    if args.target and not data.get("targetPdb"):
        target = pathlib.Path(args.target)
        if target.exists():
            data["targetPdb"] = str(target)

    req = DesignRequest.from_json(data)
    out_root = pathlib.Path(args.output)
    out_root.mkdir(parents=True, exist_ok=True)

    adapter = BoltzGenAdapter()
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
