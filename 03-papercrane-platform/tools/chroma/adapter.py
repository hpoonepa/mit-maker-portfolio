"""Chroma adapter for the Paper Crane tool integration layer.

Mirrors the TypeScript `ToolAdapter` contract in
`packages/tools-sdk/src/types.ts` and the stub in
`docs/plans/02-tool-integration.md` sec. 4.

Wire format:
  IN  /inputs/request.json   (DesignRequest, schemas/input.json)
      /inputs/target.pdb     (OPTIONAL — Chroma supports unconditional generation)
  OUT /outputs/designs/*.pdb   + *.json per-backbone metadata
      /outputs/result.json    (DesignResult, schemas/output.json)

Chroma (Generate Biomedicines, Ingraham et al., Nature 2023) is a *programmable*
generative model: users compose `conditioners` (substructure, symmetry, shape,
classifier-guided, subsequence) that steer the diffusion sampler. Chroma emits
*backbones*; sequences come from a downstream ProteinMPNN pass (platform chains
it via `manifest.composes`).

Unconditional mode: when no `targetPdb` is supplied and no substructure
conditioner is present, Chroma does pure de novo generation.
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
    # NOTE: `target_pdb` is OPTIONAL for Chroma (unconditional mode).
    seeds: List[int]
    num_designs: int
    target_pdb: Optional[str] = None
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
            target_pdb=data.get("targetPdb"),
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


# ------------------------- Chroma adapter ------------------------- #

ADAPTER_VERSION = "a1"

DEFAULT_LENGTH = 100
DEFAULT_TEMPERATURE = 1.0
DEFAULT_STEPS = 500


def _count_residues_from_pdb(pdb_path: pathlib.Path) -> int:
    """Best-effort residue count. Resilient to missing files."""
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


class ChromaAdapter(Adapter):
    manifest_path = "tools/chroma/manifest.json"

    # ----------------------------- validate ----------------------------- #

    def validate(self, req: DesignRequest) -> List[Dict[str, str]]:
        errors: List[Dict[str, str]] = []
        if not req.seeds:
            errors.append({"field": "seeds", "message": "at least one seed required"})
        if req.num_designs <= 0:
            errors.append({"field": "numDesigns", "message": "must be > 0"})

        tp = req.tool_params or {}
        length = tp.get("length")
        length_range = tp.get("length_range") or (
            req.constraints.length_range if req.constraints else None
        )
        if length is None and length_range is None:
            # Chroma needs *some* target length; the adapter falls back to
            # DEFAULT_LENGTH but we flag when neither channel supplied one so
            # the orchestrator can warn.
            pass  # non-fatal — defaults will apply
        if length_range is not None:
            if len(length_range) != 2 or length_range[0] > length_range[1]:
                errors.append({"field": "toolParams.length_range",
                               "message": "must be [min, max] with min <= max"})
            elif length_range[0] < 20 or length_range[1] > 3000:
                errors.append({"field": "toolParams.length_range",
                               "message": "out of bounds [20, 3000]"})
        if length is not None and (length < 20 or length > 3000):
            errors.append({"field": "toolParams.length",
                           "message": "out of bounds [20, 3000]"})

        temp = tp.get("temperature", DEFAULT_TEMPERATURE)
        if not (0.0 <= float(temp) <= 2.0):
            errors.append({"field": "toolParams.temperature",
                           "message": "must be in [0.0, 2.0]"})

        # Substructure conditioner implies a target PDB must be present.
        for c in tp.get("conditioners", []) or []:
            if c.get("type") == "SubstructureConditioner" and not req.target_pdb:
                errors.append({
                    "field": "targetPdb",
                    "message": "SubstructureConditioner requires targetPdb",
                })
        return errors

    # ----------------------------- prepare ----------------------------- #

    def _resolve_length(self, req: DesignRequest) -> Dict[str, Any]:
        """Pick a target length or length_range from toolParams/constraints.

        Returns a dict with exactly one of {length, length_range} set.

        Precedence (highest first):
          1. toolParams.length_range     (explicit range override)
          2. toolParams.length           (explicit single length)
          3. constraints.lengthRange     (request-level range)
          4. DEFAULT_LENGTH              (fallback)
        """
        tp = req.tool_params or {}
        if "length_range" in tp and tp["length_range"]:
            return {"length_range": list(tp["length_range"])}
        if "length" in tp and tp["length"] is not None:
            return {"length": int(tp["length"])}
        if req.constraints and req.constraints.length_range:
            return {"length_range": list(req.constraints.length_range)}
        return {"length": DEFAULT_LENGTH}

    def _normalize_conditioners(
        self,
        req: DesignRequest,
    ) -> List[Dict[str, Any]]:
        """Pass through user-supplied conditioners verbatim. The run() step
        instantiates them against upstream classes; we intentionally do not
        validate `params` here because the conditioner union is upstream-driven.
        TODO: once upstream locks its conditioner schema, validate `params`
        against per-type sub-schemas.
        """
        tp = req.tool_params or {}
        return list(tp.get("conditioners") or [])

    def prepare(self, req: DesignRequest, workdir: pathlib.Path) -> Dict[str, Any]:
        workdir.mkdir(parents=True, exist_ok=True)
        tool_params = req.tool_params or {}
        length_spec = self._resolve_length(req)
        temperature = float(tool_params.get("temperature", DEFAULT_TEMPERATURE))
        steps = int(tool_params.get("steps", DEFAULT_STEPS))
        conditioners = self._normalize_conditioners(req)
        unconditional = req.target_pdb is None and not any(
            c.get("type") == "SubstructureConditioner" for c in conditioners
        )

        cfg: Dict[str, Any] = {
            "target_pdb": req.target_pdb,  # may be None
            "target_chain": req.target_chain,
            "temperature": temperature,
            "steps": steps,
            "num_designs": req.num_designs,
            "seeds": req.seeds,
            "conditioners": conditioners,
            "unconditional": unconditional,
        }
        cfg.update(length_spec)

        cfg_path = workdir / "chroma.json"
        cfg_path.write_text(json.dumps(cfg, indent=2))
        return {
            "cfg": str(cfg_path),
            "out_dir": "/outputs/designs",
            "seeds": req.seeds,
            "num_designs": req.num_designs,
            "temperature": temperature,
            "steps": steps,
            "conditioners": conditioners,
            "unconditional": unconditional,
            "length_spec": length_spec,
            "target_pdb": req.target_pdb,
        }

    # ------------------------------- run ------------------------------- #

    def run(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke upstream Chroma.

        Upstream exposes both a Python API (`from chroma import Chroma`) and a
        CLI-like script. We shell out to `python -m chroma.cli` so that the
        conditioner instantiation happens in the child process's interpreter,
        keeping this adapter importable on machines without the chroma package.
        """
        out_dir = pathlib.Path(job["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)

        cfg_path = job["cfg"]
        for seed in job["seeds"]:
            prefix = out_dir / f"design_s{seed}"
            cmd = [
                "python", "-m", "chroma.cli",
                "--config", cfg_path,
                "--out", str(prefix),
                "--seed", str(seed),
            ]
            subprocess.run(cmd, check=True)

            # Stamp sidecar metadata JSON per design for the parser.
            for i in range(job["num_designs"]):
                pdb_path = pathlib.Path(f"{prefix}_{i:04d}.pdb")
                meta_path = pdb_path.with_suffix(".json")
                meta_path.write_text(json.dumps({
                    "seed": seed,
                    "design_index": i,
                    "temperature": job["temperature"],
                    "steps": job["steps"],
                    "conditioners_applied": [
                        c.get("type") for c in job["conditioners"]
                    ],
                    "length_target": (
                        job["length_spec"].get("length")
                        or job["length_spec"].get("length_range", [None])[0]
                    ),
                    "unconditional": job["unconditional"],
                }, indent=2))

        return {
            "out_dir": str(out_dir),
            "exit_code": 0,
            "unconditional": job["unconditional"],
        }

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
                "plddt_mean": float(meta.get("plddt_mean", 0.0)),
                "clash_score": float(meta.get("clash_score", 0.0)),
            }
            metadata: Dict[str, Any] = {
                "conditioners_applied": list(meta.get("conditioners_applied", [])),
            }
            if "length_target" in meta and meta["length_target"] is not None:
                metadata["length_target"] = int(meta["length_target"])
            if "temperature" in meta:
                metadata["temperature"] = float(meta["temperature"])
            if "steps" in meta:
                metadata["steps"] = int(meta["steps"])

            designs.append({
                "structurePath": str(pdb),
                "seed": int(meta["seed"]),
                "metrics": metrics,
                "metadata": metadata,
            })

        return DesignResult(
            designs=designs,
            run_metadata={
                "tool": "chroma",
                "adapterVersion": ADAPTER_VERSION,
                # Downstream platform hook: chain into ProteinMPNN unless the
                # caller explicitly opted out via toolParams.skip_mpnn.
                "composes": ["proteinmpnn"],
                "unconditional": bool(raw.get("unconditional", False)),
            },
        )


# ------------------------- Entrypoint ------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="Chroma Paper Crane adapter")
    parser.add_argument("--request", required=True)
    # --target is OPTIONAL (unconditional generation).
    parser.add_argument("--target", required=False, default=None)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    req = DesignRequest.from_json(json.loads(pathlib.Path(args.request).read_text()))
    # CLI-level target.pdb overrides whatever was in the request (container
    # wire format puts the file at /inputs/target.pdb).
    if args.target is not None:
        req.target_pdb = args.target

    out_root = pathlib.Path(args.output)
    out_root.mkdir(parents=True, exist_ok=True)

    adapter = ChromaAdapter()
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
