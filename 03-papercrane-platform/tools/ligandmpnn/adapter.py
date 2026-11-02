"""LigandMPNN adapter for the Paper Crane tool integration layer.

Mirrors the TypeScript `ToolAdapter` contract in
`packages/tools-sdk/src/types.ts` and the stub in
`docs/plans/02-tool-integration.md` sec. 4. Follows the same pattern as
`tools/proteinmpnn/adapter.py`, extended for LigandMPNN's ligand-aware
contract: each request MAY carry either a list of per-atom ligand
coordinates OR a path to an SDF that the scheduler stages into
/inputs/ligands/ligand.sdf.

Wire format:
  IN  /inputs/request.json  (LigandMPNN request, schemas/input.json)
      /inputs/backbones/*.pdb
      /inputs/ligands/ligand.sdf  (optional — only when `ligand_sdf` set)
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

@dataclasses.dataclass
class LigandAtom:
    residueId: str
    atomName: str
    x: float
    y: float
    z: float
    element: str


@dataclasses.dataclass
class LigandMPNNParams:
    temperature: float = 0.1
    omit_aas: str = "CX"
    num_seq_per_target: int = 1
    ligand_context_radius: float = 8.0
    fixed_positions: Optional[Dict[str, List[int]]] = None


@dataclasses.dataclass
class DesignRequest:
    backbones: List[str]
    seeds: List[int]
    params: LigandMPNNParams
    ligand_atoms: Optional[List[LigandAtom]] = None
    ligand_sdf: Optional[str] = None

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "DesignRequest":
        p = data.get("params") or {}
        params = LigandMPNNParams(
            temperature=float(p.get("temperature", 0.1)),
            omit_aas=str(p.get("omit_aas", "CX")),
            num_seq_per_target=int(p.get("num_seq_per_target", 1)),
            ligand_context_radius=float(p.get("ligand_context_radius", 8.0)),
            fixed_positions=p.get("fixed_positions"),
        )
        atoms_raw = data.get("ligand_atoms")
        atoms: Optional[List[LigandAtom]] = None
        if atoms_raw:
            atoms = [
                LigandAtom(
                    residueId=str(a["residueId"]),
                    atomName=str(a["atomName"]),
                    x=float(a["x"]),
                    y=float(a["y"]),
                    z=float(a["z"]),
                    element=str(a["element"]),
                )
                for a in atoms_raw
            ]
        return cls(
            backbones=list(data["backbones"]),
            seeds=list(data["seeds"]),
            params=params,
            ligand_atoms=atoms,
            ligand_sdf=data.get("ligand_sdf"),
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


# ------------------------- LigandMPNN adapter ------------------------- #

ADAPTER_VERSION = "a1"

# LigandMPNN FASTA header format mirrors ProteinMPNN's (see dauparas/LigandMPNN):
#   >T0_0, score=1.234, ..., seq_recovery=0.42
# We parse numeric kv pairs from the header; per-design metrics land in the
# matching .json sidecar written by the wrapper.
_FASTA_HEADER_KV = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([-0-9.eE+]+)")


class LigandMPNNAdapter(Adapter):
    manifest_path = "tools/ligandmpnn/manifest.json"

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
        if not (2.0 <= p.ligand_context_radius <= 20.0):
            errors.append({"field": "params.ligand_context_radius", "message": "must be in [2.0, 20.0]"})
        if req.ligand_atoms and req.ligand_sdf:
            errors.append({
                "field": "ligand",
                "message": "ligand_atoms and ligand_sdf are mutually exclusive",
            })
        return errors

    def prepare(self, req: DesignRequest, workdir: pathlib.Path) -> Dict[str, Any]:
        """Stage backbones + ligand context and build the LigandMPNN CLI invocation.

        Paper Crane mounts resolved backbones at /inputs/backbones and (when
        `ligand_sdf` is set) the SDF at /inputs/ligands/ligand.sdf. When
        `ligand_atoms` is set instead, we materialise them as a minimal
        HETATM-only PDB on disk so the upstream wrapper can ingest via its
        `--ligand_pdb` flag.
        """
        workdir.mkdir(parents=True, exist_ok=True)

        pdb_dir = workdir / "pdbs"
        pdb_dir.mkdir(parents=True, exist_ok=True)

        job: Dict[str, Any] = {
            "pdb_dir": str(pdb_dir),
            "out_dir": "/outputs/designs",
            "num_seq_per_target": req.params.num_seq_per_target,
            "sampling_temp": req.params.temperature,
            "omit_aas": req.params.omit_aas,
            "ligand_context_radius": req.params.ligand_context_radius,
            "seeds": req.seeds,
            "backbones": list(req.backbones),
        }

        if req.ligand_atoms:
            ligand_pdb = workdir / "ligand.pdb"
            ligand_pdb.write_text(_atoms_to_pdb(req.ligand_atoms))
            job["ligand_pdb"] = str(ligand_pdb)
        elif req.ligand_sdf:
            # The scheduler stages the resolved file at /inputs/ligands/ligand.sdf;
            # record its target path so run() can point LigandMPNN at it.
            job["ligand_pdb"] = "/inputs/ligands/ligand.sdf"

        if req.params.fixed_positions:
            fp_path = workdir / "fixed_positions.json"
            fp_path.write_text(json.dumps(req.params.fixed_positions, indent=2))
            job["fixed_positions_jsonl"] = str(fp_path)
        return job

    def run(self, job: Dict[str, Any]) -> Dict[str, Any]:
        out_dir = pathlib.Path(job["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        base_cmd: List[str] = [
            "python", "/opt/ligandmpnn/run.py",
            "--pdb_path", job["pdb_dir"],
            "--out_folder", str(out_dir),
            "--num_seq_per_target", str(job["num_seq_per_target"]),
            "--sampling_temp", str(job["sampling_temp"]),
            "--omit_AAs", job["omit_aas"],
            "--ligand_context_radius", str(job["ligand_context_radius"]),
        ]
        if job.get("ligand_pdb"):
            base_cmd += ["--ligand_pdb", job["ligand_pdb"]]
        if job.get("fixed_positions_jsonl"):
            base_cmd += ["--fixed_positions_jsonl", job["fixed_positions_jsonl"]]
        # LigandMPNN takes a single seed per invocation; loop to honor the
        # full seed list. Each run appends to the same out_folder.
        for seed in job["seeds"]:
            subprocess.run(base_cmd + ["--seed", str(seed)], check=True)
        return {"out_dir": str(out_dir), "exit_code": 0}

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
            metrics: Dict[str, float] = {
                "score": float(meta.get("score", 0.0)),
                "confidence_mean": float(meta.get("confidence_mean", 0.0)),
            }
            if "ligand_context_residues" in meta:
                metrics["ligand_context_residues"] = float(
                    meta["ligand_context_residues"]
                )
            design: Dict[str, Any] = {
                "structurePath": meta.get("structurePath", ""),
                "sequence": sequence,
                "metrics": metrics,
                "seed": int(meta.get("seed", 0)),
            }
            if meta.get("ligandPath"):
                design["ligandPath"] = meta["ligandPath"]
            designs.append(design)
        return DesignResult(
            designs=designs,
            run_metadata={"tool": "ligandmpnn", "adapterVersion": ADAPTER_VERSION},
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


def _atoms_to_pdb(atoms: List[LigandAtom]) -> str:
    """Serialize raw LigandAtom records into a minimal HETATM-only PDB.

    LigandMPNN's wrapper accepts a standard PDB for the ligand and looks only
    at HETATM records; we emit the bare minimum fields required.
    """
    lines: List[str] = []
    for i, a in enumerate(atoms, start=1):
        # Parse chain + resi out of residueId like 'A1' or 'B123'.
        chain = a.residueId[0] if a.residueId else "L"
        try:
            resi = int(a.residueId[1:]) if len(a.residueId) > 1 else i
        except ValueError:
            resi = i
        lines.append(
            f"HETATM{i:>5d} {a.atomName:>4s} LIG {chain}{resi:>4d}    "
            f"{a.x:8.3f}{a.y:8.3f}{a.z:8.3f}  1.00  0.00          {a.element:>2s}"
        )
    lines.append("END")
    return "\n".join(lines) + "\n"


# ------------------------- Entrypoint ------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="LigandMPNN Paper Crane adapter")
    parser.add_argument("--request", required=True)
    parser.add_argument("--backbones", required=True,
                        help="Directory of staged backbone PDBs (mounted by scheduler).")
    parser.add_argument("--ligands", required=False, default="/inputs/ligands",
                        help="Directory of staged ligand files (optional).")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    req = DesignRequest.from_json(json.loads(pathlib.Path(args.request).read_text()))
    out_root = pathlib.Path(args.output)
    out_root.mkdir(parents=True, exist_ok=True)

    adapter = LigandMPNNAdapter()
    errors = adapter.validate(req)
    if errors:
        (out_root / "errors.json").write_text(json.dumps({"errors": errors}, indent=2))
        print(json.dumps({"errors": errors}), flush=True)
        return 2

    job = adapter.prepare(req, out_root / "workdir")
    # The scheduler has already staged backbones into args.backbones; point
    # the job at that directory rather than the workdir scratch path so the
    # upstream CLI sees the real inputs. If the request referenced an SDF, the
    # scheduler placed it under args.ligands; recompute the expected path.
    job["pdb_dir"] = args.backbones
    if req.ligand_sdf:
        job["ligand_pdb"] = str(pathlib.Path(args.ligands) / "ligand.sdf")
    raw = adapter.run(job)
    result = adapter.parse(raw)
    (out_root / "result.json").write_text(json.dumps(result.to_json(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
