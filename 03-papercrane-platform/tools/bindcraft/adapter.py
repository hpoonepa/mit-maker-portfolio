"""BindCraft adapter for the Paper Crane tool integration layer.

Mirrors the TypeScript `ToolAdapter` contract in
`packages/tools-sdk/src/types.ts`.

Wire format:
  IN  /inputs/request.json  (DesignRequest, schemas/input.json)
      /inputs/target.pdb
  OUT /outputs/designs/*.pdb  + *.json per-design metrics
      /outputs/result.json   (DesignResult, schemas/output.json)
"""
from __future__ import annotations

import json
import pathlib
import subprocess
from typing import Any, Dict, List

from papercrane_sdk import (
    Adapter,
    Design,
    DesignConstraints,  # re-exported for type-hints / downstream import parity
    DesignRequest,
    DesignResult,
    Residue,  # re-exported for type-hints / downstream import parity
    RunMetadata,
    ToolManifest,
    ValidationError,
    run_cli,
)

# Unused imports above are kept so other modules or typing tooling importing
# them from this adapter file still resolve. Mark as "noqa" to keep linters
# quiet without silencing everything.
_ = (Residue, DesignConstraints, ToolManifest)


# ------------------------- BindCraft adapter ------------------------- #

ADAPTER_VERSION = "a1"


class BindCraftAdapter(Adapter):
    # Manifest is loaded from tools/bindcraft/manifest.json by the host; the
    # class attribute is populated by the SDK's manifest loader at CLI boot.
    # Kept as a bare forward declaration so static type-checkers see the
    # attribute — `run_cli` does not require it to be pre-populated.
    manifest: ToolManifest

    def validate(self, req: DesignRequest) -> List[ValidationError]:
        # Layer tool-specific rules on top of the SDK-wide defaults.
        errors: List[ValidationError] = list(super().validate(req))
        if not req.seeds:
            errors.append(ValidationError(field="seeds", message="at least one seed required"))
        if req.num_designs <= 0:
            errors.append(ValidationError(field="numDesigns", message="must be > 0"))
        if req.constraints and req.constraints.length_range:
            lo, hi = req.constraints.length_range
            if lo < 20 or hi > 300 or lo > hi:
                errors.append(
                    ValidationError(
                        field="constraints.lengthRange",
                        message="invalid length range",
                    )
                )
        return errors

    def prepare(self, req: DesignRequest, workdir: pathlib.Path) -> Dict[str, Any]:
        workdir.mkdir(parents=True, exist_ok=True)
        length_range = (
            list(req.constraints.length_range)
            if req.constraints and req.constraints.length_range
            else [60, 150]
        )
        cfg: Dict[str, Any] = {
            "target_pdb": "/inputs/target.pdb",
            "target_chain": req.target_chain or "A",
            "hotspots": [f"{h.chain}{h.resi}" for h in (req.hotspots or [])],
            "binder_length_range": length_range,
            "num_designs": req.num_designs,
            "seeds": req.seeds,
        }
        # Merge tool-specific escape-hatch knobs.
        for k, v in (req.tool_params or {}).items():
            cfg.setdefault(k, v)

        cfg_path = workdir / "bindcraft.json"
        cfg_path.write_text(json.dumps(cfg, indent=2))
        return {"cfg": str(cfg_path), "out_dir": "/outputs/designs"}

    def run(self, job: Dict[str, Any]) -> Dict[str, Any]:
        out_dir = pathlib.Path(job["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "python", "/opt/bindcraft/bindcraft.py",
                "--config", job["cfg"],
                "--out", str(out_dir),
            ],
            check=True,
        )
        return {"out_dir": str(out_dir), "exit_code": 0}

    def parse(self, raw: Dict[str, Any]) -> DesignResult:
        designs: List[Design] = []
        out_dir = pathlib.Path(raw["out_dir"])
        for pdb in sorted(out_dir.glob("*.pdb")):
            meta_path = pdb.with_suffix(".json")
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text())
            designs.append(
                Design(
                    structurePath=str(pdb),
                    sequence=meta["sequence"],
                    metrics={
                        "iptm": float(meta.get("iptm", 0.0)),
                        "plddt": float(meta.get("plddt", 0.0)),
                        "i_pae": float(meta.get("i_pae", 0.0)),
                        "hotspot_contact": float(meta.get("hs_contact", 0.0)),
                    },
                    seed=int(meta["seed"]),
                )
            )
        return DesignResult(
            designs=designs,
            runMetadata=RunMetadata(tool="bindcraft", adapterVersion=ADAPTER_VERSION),
        )


# ------------------------- Entrypoint ------------------------- #

if __name__ == "__main__":
    raise SystemExit(run_cli(BindCraftAdapter))
