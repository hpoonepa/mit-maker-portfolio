"""Germinal adapter for the Paper Crane tool integration layer.

De novo epitope-targeted antibody / nanobody (VHH / scFv) design. Mirrors the
TypeScript `ToolAdapter` contract in `packages/tools-sdk/src/types.ts`.

LICENSE NOTE: Germinal's code is Apache-2.0 but it depends on IgLM (JHU
non-commercial academic license) and PyRosetta (non-commercial). The effective
license is NON-COMMERCIAL — the manifest flags this with `licenseGate: true`
so the platform gate blocks it from the commercial tier.

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


# ------------------------- Germinal adapter ------------------------- #

ADAPTER_VERSION = "a1"

# Antibody framework types supported by Germinal.
FRAMEWORK_TYPES = {"VHH", "scFv"}


class GerminalAdapter(Adapter):
    # Manifest is loaded from tools/germinal/manifest.json by the host; the
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
        framework = str((req.tool_params or {}).get("frameworkType", "VHH"))
        if framework not in FRAMEWORK_TYPES:
            errors.append(
                ValidationError(
                    field="frameworkType",
                    message=f"must be one of {sorted(FRAMEWORK_TYPES)}",
                )
            )
        return errors

    def prepare(self, req: DesignRequest, workdir: pathlib.Path) -> Dict[str, Any]:
        workdir.mkdir(parents=True, exist_ok=True)
        framework = str((req.tool_params or {}).get("frameworkType", "VHH"))
        cfg: Dict[str, Any] = {
            "target_pdb": "/inputs/target.pdb",
            "target_chain": req.target_chain or "A",
            "hotspots": [f"{h.chain}{h.resi}" for h in (req.hotspots or [])],
            "framework_type": framework,
            "num_designs": req.num_designs,
            "seeds": req.seeds,
        }
        # Merge tool-specific escape-hatch knobs.
        for k, v in (req.tool_params or {}).items():
            cfg.setdefault(k, v)

        cfg_path = workdir / "germinal.json"
        cfg_path.write_text(json.dumps(cfg, indent=2))
        return {"cfg": str(cfg_path), "out_dir": "/outputs/designs"}

    def run(self, job: Dict[str, Any]) -> Dict[str, Any]:
        out_dir = pathlib.Path(job["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "python", "/opt/germinal/germinal.py",
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
            runMetadata=RunMetadata(tool="germinal", adapterVersion=ADAPTER_VERSION),
        )


# ------------------------- Entrypoint ------------------------- #

if __name__ == "__main__":
    raise SystemExit(run_cli(GerminalAdapter))
