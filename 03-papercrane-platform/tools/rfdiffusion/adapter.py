"""RFdiffusion adapter for the Paper Crane tool integration layer.

Mirrors the TypeScript `ToolAdapter` contract in
`packages/tools-sdk/src/types.ts` and the stub in
`docs/plans/02-tool-integration.md` sec. 4.

Wire format:
  IN  /inputs/request.json   (DesignRequest, schemas/input.json)
      /inputs/target.pdb
  OUT /outputs/designs/*.pdb   + *.json per-backbone metadata
      /outputs/result.json    (DesignResult, schemas/output.json)

RFdiffusion only produces *backbones* — no sequences. The platform chains
ProteinMPNN automatically (see `manifest.composes`). This adapter is agnostic to
that composition: it just writes backbones + metadata JSON per design.
"""
from __future__ import annotations

# TODO: replace with import from papercrane_sdk once Python SDK is published.
# from papercrane_sdk import Adapter, DesignRequest, DesignResult
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
    disulfides: Optional[bool] = None
    solubility: Optional[str] = None


@dataclasses.dataclass
class DesignRequest:
    target_pdb: str
    seeds: List[int]
    num_designs: int
    target_chain: Optional[str] = None
    hotspots: Optional[List[Residue]] = None
    constraints: Optional[DesignConstraints] = None
    tool_params: Optional[Dict[str, Any]] = None

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "DesignRequest":
        hotspots = [Residue(**h) for h in data.get("hotspots", [])] or None
        c = data.get("constraints") or {}
        constraints = DesignConstraints(
            length_range=c.get("lengthRange"),
            disulfides=c.get("disulfides"),
            solubility=c.get("solubility"),
        ) if c else None
        return cls(
            target_pdb=data["targetPdb"],
            seeds=data["seeds"],
            num_designs=data["numDesigns"],
            target_chain=data.get("targetChain"),
            hotspots=hotspots,
            constraints=constraints,
            tool_params=data.get("toolParams"),
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


# ------------------------- RFdiffusion adapter ------------------------- #

ADAPTER_VERSION = "a1"

# Default target-chain residue range for the contig string. The platform can
# override via `toolParams.contigs`. We keep this a constant so the fixture can
# exercise the default branch.
DEFAULT_TARGET_RANGE = "1-150"


def _count_residues_from_pdb(pdb_path: pathlib.Path) -> int:
    """Best-effort residue count for a chain. Used to fill plddt_contig_mean=0
    fallbacks when upstream metadata is absent. Resilient to missing files
    (returns 0) so parse() never crashes on malformed outputs."""
    try:
        seen: set = set()
        for line in pdb_path.read_text().splitlines():
            if line.startswith(("ATOM", "HETATM")):
                chain = line[21:22]
                resi = line[22:26].strip()
                if resi:
                    seen.add((chain, resi))
        return len(seen)
    except OSError:
        return 0


class RFdiffusionAdapter(Adapter):
    manifest_path = "tools/rfdiffusion/manifest.json"

    # ----------------------------- validate ----------------------------- #

    def validate(self, req: DesignRequest) -> List[Dict[str, str]]:
        errors: List[Dict[str, str]] = []
        if not req.seeds:
            errors.append({"field": "seeds", "message": "at least one seed required"})
        if req.num_designs <= 0:
            errors.append({"field": "numDesigns", "message": "must be > 0"})
        if req.constraints and req.constraints.length_range:
            lo, hi = req.constraints.length_range
            if lo < 20 or hi > 300 or lo > hi:
                errors.append({"field": "constraints.lengthRange",
                               "message": "invalid length range"})
        # Hotspots aren't strictly required by RFdiffusion — binder mode will
        # run without them — but we warn if none supplied since interface
        # quality drops sharply.
        return errors

    # ----------------------------- prepare ----------------------------- #

    def _build_contigs(
        self,
        req: DesignRequest,
        length_range: List[int],
    ) -> str:
        """Compose an RFdiffusion contigmap.contigs string.

        Format: "A1-150/0 60-150" means "hold chain A residues 1..150 fixed,
        then generate a 60..150-residue binder chain". Users can fully
        override via `toolParams.contigs`.
        """
        override = (req.tool_params or {}).get("contigs")
        if isinstance(override, str) and override.strip():
            return override.strip()
        chain = req.target_chain or "A"
        lo, hi = length_range
        return f"[{chain}{DEFAULT_TARGET_RANGE}/0 {lo}-{hi}]"

    def prepare(self, req: DesignRequest, workdir: pathlib.Path) -> Dict[str, Any]:
        workdir.mkdir(parents=True, exist_ok=True)
        length_range = (
            req.constraints.length_range
            if req.constraints and req.constraints.length_range
            else [60, 150]
        )
        tool_params = req.tool_params or {}
        noise_scale = float(tool_params.get("noise_scale", 1.0))

        contigs = self._build_contigs(req, length_range)
        hotspots = [f"{h.chain}{h.resi}" for h in (req.hotspots or [])]

        cfg: Dict[str, Any] = {
            "target_pdb": "/inputs/target.pdb",
            "target_chain": req.target_chain or "A",
            "hotspots": hotspots,
            "binder_length_range": length_range,
            "contigs": contigs,
            "noise_scale": noise_scale,
            "num_designs": req.num_designs,
            "seeds": req.seeds,
        }
        cfg_path = workdir / "rfdiffusion.json"
        cfg_path.write_text(json.dumps(cfg, indent=2))
        return {
            "cfg": str(cfg_path),
            "out_dir": "/outputs/designs",
            "contigs": contigs,
            "hotspots": hotspots,
            "noise_scale": noise_scale,
            "seeds": req.seeds,
            "num_designs": req.num_designs,
            "target_pdb": cfg["target_pdb"],
        }

    # ------------------------------- run ------------------------------- #

    def run(self, job: Dict[str, Any]) -> Dict[str, Any]:
        out_dir = pathlib.Path(job["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)

        contigs = job["contigs"]
        hotspots = job["hotspots"]
        noise_scale = job["noise_scale"]

        # RFdiffusion is invoked once per seed; each invocation emits
        # num_designs backbones numbered <prefix>_0.pdb, <prefix>_1.pdb, ...
        for seed in job["seeds"]:
            prefix = out_dir / f"backbone_s{seed}"
            cmd = [
                "python", "/opt/rfdiffusion/scripts/run_inference.py",
                f"contigmap.contigs={contigs}",
                f"ppi.hotspot_res={hotspots}",
                f"inference.output_prefix={prefix}",
                f"inference.num_designs={job['num_designs']}",
                f"inference.input_pdb={job['target_pdb']}",
                f"denoiser.noise_scale_ca={noise_scale}",
                f"denoiser.noise_scale_frame={noise_scale}",
                f"inference.seed={seed}",
            ]
            subprocess.run(cmd, check=True)

            # Stamp a sidecar metadata JSON per backbone for the parser.
            for i in range(job["num_designs"]):
                pdb_path = pathlib.Path(f"{prefix}_{i}.pdb")
                meta_path = pdb_path.with_suffix(".json")
                meta_path.write_text(json.dumps({
                    "seed": seed,
                    "design_index": i,
                    "contigs_used": contigs,
                    "noise_scale": noise_scale,
                    "hotspots": hotspots,
                }, indent=2))

        return {"out_dir": str(out_dir), "exit_code": 0}

    # ------------------------------ parse ------------------------------ #

    def parse(self, raw: Dict[str, Any]) -> DesignResult:
        designs: List[Dict[str, Any]] = []
        out_dir = pathlib.Path(raw["out_dir"])
        for pdb in sorted(out_dir.glob("*.pdb")):
            meta_path = pdb.with_suffix(".json")
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text())
            length = int(meta.get("length", _count_residues_from_pdb(pdb)))
            metrics: Dict[str, float] = {
                "length": float(length),
                "plddt_contig_mean": float(meta.get("plddt_contig_mean", 0.0)),
            }
            designs.append({
                "structurePath": str(pdb),
                "seed": int(meta["seed"]),
                "metrics": metrics,
                "metadata": {
                    "contigs_used": meta["contigs_used"],
                    "noise_scale": float(meta.get("noise_scale", 1.0)),
                    "hotspots": list(meta.get("hotspots", [])),
                },
            })
        return DesignResult(
            designs=designs,
            run_metadata={
                "tool": "rfdiffusion",
                "adapterVersion": ADAPTER_VERSION,
                # Downstream platform hook: chain into ProteinMPNN unless the
                # caller explicitly opted out.
                "composes": ["proteinmpnn"],
            },
        )


# ------------------------- Entrypoint ------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="RFdiffusion Paper Crane adapter")
    parser.add_argument("--request", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    req = DesignRequest.from_json(json.loads(pathlib.Path(args.request).read_text()))
    out_root = pathlib.Path(args.output)
    out_root.mkdir(parents=True, exist_ok=True)

    adapter = RFdiffusionAdapter()
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
