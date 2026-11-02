# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "modal>=1.0",
# ]
# ///
"""Paper Crane LigandMPNN Modal app.

Ligand-aware variant of ProteinMPNN. Designs protein sequences conditioned on
the surrounding small-molecule context (HETATM records in the input PDB), so
active-site / binding-pocket residues are sampled in the presence of their
cofactor or ligand rather than in vacuum.

Upstream: https://github.com/dauparas/LigandMPNN
Reference: Dauparas, J. et al. "Atomic context-conditioned protein sequence
design using LigandMPNN" (2025).

Wire format matches the rest of the Paper Crane tool layer:
  • `predict(input_pdb, seeds, params)` for direct calls.
  • `papercrane_dispatch(job_id, seeds, params, prev_output)` for the worker
    `_modalRunner.ts` NDJSON contract (one `{type:"seed",...}` per seed, then
    a `{type:"done", summary:{...}}` terminator).

GPU: A10 — LigandMPNN is a small MPNN-style model (~50 MB weights, runs in
~5-10 s per design), so A10 is plenty and keeps cost low.

Weights are cached in the `papercrane-ligandmpnn-cache` Modal volume so we
don't redownload on every cold start.

Test:
    modal run tools/ligandmpnn/modal_app.py
"""
import json
import os
import re
from pathlib import Path

import modal

GPU = os.environ.get("GPU", "A10")
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", 30))

# Pin the upstream commit so reproducibility doesn't drift with HEAD. Bump in
# sync with the Dockerfile's LIGANDMPNN_SHA build arg when we cut new images.
# Last commit on dauparas/LigandMPNN main as of 2026-06-02 (commit date
# 2025-02-06, merge of #37 fixed_residues_multi bug fix). Verified via
# `gh api repos/dauparas/LigandMPNN/commits/main`.
LIGANDMPNN_REPO = "https://github.com/dauparas/LigandMPNN.git"
LIGANDMPNN_SHA = os.environ.get(
    "LIGANDMPNN_SHA", "26ec57ac976ade5379920dbd43c7f97a91cf82de"
)
LIGANDMPNN_DIR = "/opt/ligandmpnn"

CACHE_VOLUME_NAME = "papercrane-ligandmpnn-cache"
CACHE_VOLUME = modal.Volume.from_name(CACHE_VOLUME_NAME, create_if_missing=True)
CACHE_DIR = f"/{CACHE_VOLUME_NAME}"  # weights land at /papercrane-ligandmpnn-cache/

# Smoke test: 56-aa fragment of human ubiquitin (chain A of 1UBQ). We pair it
# with a single fake C-alpha HETATM so the run exercises the ligand path even
# when the caller hasn't supplied a real cofactor.
SMOKE_SEQUENCE = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTL"


# --------------------------- weights & image --------------------------- #

def _download_weights() -> None:
    """Pull LigandMPNN model parameters into the cache volume (one-time).

    The upstream repo ships a `get_model_params.sh` helper that downloads the
    full set (~50 MB) into `model_params/`. We mirror that into the volume
    under `model_params/` so subsequent cold starts are weight-free.
    """
    import subprocess

    cache_root = Path(CACHE_DIR)
    cache_root.mkdir(parents=True, exist_ok=True)
    weights_root = cache_root / "model_params"
    # Heuristic: if the directory exists and isn't empty, assume cached.
    if weights_root.exists() and any(weights_root.iterdir()):
        print(f"LigandMPNN weights already cached at {weights_root}")
        return

    print(f"Downloading LigandMPNN weights into {weights_root} ...")
    weights_root.mkdir(parents=True, exist_ok=True)
    script = Path(LIGANDMPNN_DIR) / "get_model_params.sh"
    if script.exists():
        # The upstream script takes a destination dir as $1.
        subprocess.run(
            ["bash", str(script), str(weights_root)],
            check=True,
            cwd=LIGANDMPNN_DIR,
        )
    else:
        # Fallback: known-good public bucket layout used by the upstream repo.
        # Keeping the URL list narrow so we don't silently grab unrelated files.
        import urllib.request
        base = "https://files.ipd.uw.edu/pub/ligandmpnn"
        for name in [
            "ligandmpnn_v_32_010_25.pt",
            "ligandmpnn_v_32_020_25.pt",
            "ligandmpnn_v_32_030_25.pt",
            "proteinmpnn_v_48_002.pt",
            "proteinmpnn_v_48_010.pt",
            "proteinmpnn_v_48_020.pt",
            "proteinmpnn_v_48_030.pt",
            "global_label_membrane_mpnn_v_48_020.pt",
            "per_residue_label_membrane_mpnn_v_48_020.pt",
            "solublempnn_v_48_010.pt",
            "solublempnn_v_48_020.pt",
            "solublempnn_v_48_030.pt",
        ]:
            dest = weights_root / name
            if dest.exists():
                continue
            url = f"{base}/{name}"
            print(f"  fetching {url}")
            try:
                urllib.request.urlretrieve(url, dest)
            except Exception as exc:
                print(f"  WARN: could not fetch {name}: {exc}")
    print("Done.")


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "wget", "build-essential")
    .pip_install(
        # LigandMPNN inference is light: torch + numpy + biopython for PDB IO.
        # Pin to CUDA 12.1 wheels matching the A10 driver in Modal's base.
        "torch==2.2.1",
        "numpy==1.26.4",
        "biopython==1.83",
        "ProDy==2.4.1",
        "filelock",
    )
    .run_commands(
        f"git clone {LIGANDMPNN_REPO} {LIGANDMPNN_DIR}",
        f"cd {LIGANDMPNN_DIR} && git checkout {LIGANDMPNN_SHA}",
    )
    .run_function(
        _download_weights,
        volumes={CACHE_DIR: CACHE_VOLUME},
    )
)

app = modal.App("ligandmpnn", image=image)


# --------------------------- helpers --------------------------- #

# LigandMPNN's FASTA header (run.py) encodes per-design metrics inline, e.g.:
#   >id, T=0.10, seed=42, overall_confidence=0.78, ligand_confidence=0.81,
#    sample=1, score=1.234, global_score=1.456, seq_recovery=0.42
_FASTA_HEADER_KV = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([-0-9.eE+]+)")


def _emit_event(event: dict) -> None:
    """NDJSON line writer for the worker stream."""
    print(json.dumps(event), flush=True)


def _json_arg(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _numeric_metrics(metrics: dict) -> dict:
    return {k: v for k, v in metrics.items() if isinstance(v, (int, float))}


def _parse_fasta(fasta_path: Path) -> list[dict]:
    """Yield one record per FASTA entry: {header, kv_metrics, sequence}.

    LigandMPNN emits one FASTA per input PDB with the original sequence first
    and `num_seq_per_target` redesigns after it. We keep them all so the caller
    can pick the top sample; the metrics dict comes from the header.
    """
    records: list[dict] = []
    header: str | None = None
    seq_lines: list[str] = []

    def _flush() -> None:
        if header is None:
            return
        seq = "".join(s.strip() for s in seq_lines)
        kv: dict[str, float] = {}
        for m in _FASTA_HEADER_KV.finditer(header):
            try:
                kv[m.group(1)] = float(m.group(2))
            except ValueError:
                continue
        records.append({"header": header, "metrics": kv, "sequence": seq})

    for raw in fasta_path.read_text().splitlines():
        line = raw.rstrip()
        if line.startswith(">"):
            _flush()
            header = line[1:].strip()
            seq_lines = []
        elif line:
            seq_lines.append(line)
    _flush()
    return records


def _aggregate_metrics(records: list[dict]) -> tuple[dict, dict]:
    """Pick the best (lowest-score) design and surface key per-seed metrics.

    LigandMPNN scores are negative log-likelihoods (lower is better). We pull
    the canonical fields the rest of the Paper Crane stack wants
    (sample_perplexity, global_score, recovery) and fall back to whatever's in
    the header if a key is absent (e.g. older LigandMPNN versions).

    Returns:
        (metrics, best_record) — `metrics` is a flat numeric dict suitable for
        the NDJSON event, `best_record` is the full record (header + sequence)
        so callers can extract the designed sequence text.
    """
    # Skip the first record — LigandMPNN writes the input WT sequence as
    # record 0 with score=0; designs start at record 1.
    designs = [r for r in records if r["metrics"].get("sample", 0) >= 1] or records
    if not designs:
        return {}, {}

    # Best = lowest `score` (a.k.a. NLL).
    def _score(r: dict) -> float:
        return float(r["metrics"].get("score", float("inf")))

    best = min(designs, key=_score)
    m = best["metrics"]
    out: dict[str, float] = {}
    # Map upstream field -> Paper Crane canonical name.
    aliases = {
        "sample_perplexity": ("sample_perplexity", "perplexity"),
        "global_score": ("global_score",),
        "score": ("score",),
        "recovery": ("seq_recovery", "recovery"),
        "overall_confidence": ("overall_confidence",),
        "ligand_confidence": ("ligand_confidence",),
        "T": ("T", "temperature"),
    }
    for canonical, candidates in aliases.items():
        for c in candidates:
            if c in m:
                out[canonical] = float(m[c])
                break
    return out, best


# --------------------------- core inference --------------------------- #

@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    volumes={CACHE_DIR: CACHE_VOLUME},
)
def predict(
    job_id: str = "smoke",
    params: dict | None = None,
    seeds: list[int] | None = None,
) -> dict:
    """Run LigandMPNN for each seed in `seeds`.

    Args:
        job_id: Used only for namespacing artifact paths in the returned dict.
        params: {
            input_pdb: str | bytes | None   # PDB body (with HETATM ligand) or path
            chains_to_design: str           # e.g. "A" or "A,B"
            fixed_positions: dict[str, list[int]] | None
            redesigned_residues: dict[str, list[int]] | None
            num_seq_per_target: int = 1
            temperature: float = 0.1
            omit_aas: str = "CX"
            ligand_context_radius: float = 8.0
            model_type: str = "ligand_mpnn"   # or "protein_mpnn" / "soluble_mpnn"
            checkpoint: str | None            # override .pt filename in cache
        }
        seeds: List of integer seeds; LigandMPNN takes one per run.

    Returns:
        {
          job_id,
          seeds: [
            {
              seed: int,
              fasta_text: str,
              metrics: {sample_perplexity, global_score, recovery, ...},
              best_sequence: str,
              artifactKey: str,
            }, ...
          ],
        }
    """
    return _predict_impl(job_id=job_id, params=params or {}, seeds=seeds or [0])


def _predict_impl(job_id: str, params: dict, seeds: list[int]) -> dict:
    from subprocess import run as sp_run
    from tempfile import TemporaryDirectory

    input_pdb = params.get("input_pdb")
    if not input_pdb:
        # Smoke fallback: write a tiny stub PDB so the runner exercises end to
        # end. The "ligand" here is a single HETATM zinc placed near the
        # N-terminus so LigandMPNN has *something* to condition on.
        input_pdb = _smoke_pdb(SMOKE_SEQUENCE)

    chains_to_design = str(params.get("chains_to_design", "A"))
    num_seq = int(params.get("num_seq_per_target", 1))
    temperature = float(params.get("temperature", 0.1))
    omit_aas = str(params.get("omit_aas", "CX"))
    ligand_radius = float(params.get("ligand_context_radius", 8.0))
    model_type = str(params.get("model_type", "ligand_mpnn"))
    fixed_positions = params.get("fixed_positions") or {}
    redesigned_residues = params.get("redesigned_residues") or {}
    checkpoint_override = params.get("checkpoint")

    # Resolve checkpoint path within the cache volume.
    weights_root = Path(CACHE_DIR) / "model_params"
    if checkpoint_override:
        ckpt = weights_root / checkpoint_override
    else:
        ckpt = _default_checkpoint(model_type, weights_root)

    seed_results: list[dict] = []

    with TemporaryDirectory() as td:
        td_path = Path(td)
        pdb_path = td_path / "input.pdb"
        if isinstance(input_pdb, (bytes, bytearray)):
            pdb_path.write_bytes(bytes(input_pdb))
        elif isinstance(input_pdb, str) and input_pdb.lstrip().startswith(
            ("HEADER", "ATOM", "HETATM", "MODEL", "REMARK")
        ):
            pdb_path.write_text(input_pdb)
        else:
            # Treat as a filesystem path that's already mounted into the
            # container (e.g. via the scheduler's /inputs staging).
            pdb_path.write_text(Path(input_pdb).read_text())

        # LigandMPNN's run.py expects JSONL for fixed positions; we keep it
        # simple and serialize as JSON — both forms parse upstream.
        fp_path = td_path / "fixed_positions.json"
        if fixed_positions:
            fp_path.write_text(json.dumps(fixed_positions))
        rr_path = td_path / "redesigned_residues.json"
        if redesigned_residues:
            rr_path.write_text(json.dumps(redesigned_residues))

        for seed in seeds:
            out_dir = td_path / f"out_{seed}"
            out_dir.mkdir(parents=True, exist_ok=True)

            cmd = [
                "python", f"{LIGANDMPNN_DIR}/run.py",
                "--model_type", model_type,
                "--checkpoint_ligand_mpnn", str(ckpt) if model_type == "ligand_mpnn" else "",
                "--checkpoint_protein_mpnn", str(ckpt) if model_type == "protein_mpnn" else "",
                "--checkpoint_soluble_mpnn", str(ckpt) if model_type == "soluble_mpnn" else "",
                "--pdb_path", str(pdb_path),
                "--out_folder", str(out_dir),
                "--seed", str(seed),
                "--batch_size", "1",
                "--number_of_batches", str(max(1, num_seq)),
                "--temperature", str(temperature),
                "--omit_AA", omit_aas,
                "--ligand_mpnn_cutoff_for_score", str(ligand_radius),
                "--chains_to_design", chains_to_design,
                "--save_stats", "1",
            ]
            # Drop empty checkpoint flags so we don't pass `--... ""`.
            cleaned: list[str] = []
            skip_next = False
            for tok in cmd:
                if skip_next:
                    skip_next = False
                    if tok == "":
                        cleaned.pop()  # drop the matching flag
                        continue
                    cleaned.append(tok)
                    continue
                if tok.startswith("--checkpoint_"):
                    skip_next = True
                cleaned.append(tok)
            cmd = cleaned

            if fixed_positions:
                cmd += ["--fixed_residues", _flatten_positions(fixed_positions)]
            if redesigned_residues:
                cmd += ["--redesigned_residues", _flatten_positions(redesigned_residues)]

            print(f"[ligandmpnn] seed={seed} cmd={' '.join(cmd)}")
            sp_run(cmd, check=True)

            fasta_files = sorted((out_dir / "seqs").glob("*.fa")) + sorted(
                (out_dir / "seqs").glob("*.fasta")
            )
            if not fasta_files:
                # Some LigandMPNN forks drop FASTAs directly in out_folder.
                fasta_files = sorted(out_dir.glob("*.fa")) + sorted(out_dir.glob("*.fasta"))
            if not fasta_files:
                raise RuntimeError(
                    f"LigandMPNN produced no FASTA for seed={seed} in {out_dir}"
                )
            fasta_path = fasta_files[0]
            records = _parse_fasta(fasta_path)
            metrics, best = _aggregate_metrics(records)
            seed_results.append({
                "seed": int(seed),
                "fasta_text": fasta_path.read_text(),
                "metrics": metrics,
                "best_sequence": best.get("sequence", ""),
                "best_header": best.get("header", ""),
                "artifactKey": f"jobs/{job_id}/designs/{seed}.fasta",
            })

    return {"job_id": job_id, "seeds": seed_results}


def _default_checkpoint(model_type: str, weights_root: Path) -> Path:
    """Return the canonical checkpoint filename per model_type.

    These match the names produced by `get_model_params.sh` in the upstream
    repo as of 2025-06. If the user pre-mounted a different layout, they can
    override via `params.checkpoint`.
    """
    defaults = {
        "ligand_mpnn": "ligandmpnn_v_32_010_25.pt",
        "protein_mpnn": "proteinmpnn_v_48_020.pt",
        "soluble_mpnn": "solublempnn_v_48_020.pt",
    }
    name = defaults.get(model_type, defaults["ligand_mpnn"])
    return weights_root / name


def _flatten_positions(per_chain: dict) -> str:
    """Convert {'A': [1,2,3]} into LigandMPNN's `A1 A2 A3` CLI argument."""
    parts: list[str] = []
    for chain, resis in per_chain.items():
        for r in resis:
            parts.append(f"{chain}{int(r)}")
    return " ".join(parts)


def _smoke_pdb(sequence: str) -> str:
    """Tiny ATOM-only PDB with a single Zn HETATM, just for smoke tests."""
    # We don't need real geometry — LigandMPNN's structure-aware path still
    # runs on placeholder coordinates as long as the file parses. This is
    # purely so the smoke test exercises the pipeline end-to-end.
    lines: list[str] = []
    for i, aa in enumerate(sequence, start=1):
        x = float(i) * 3.8
        lines.append(
            f"ATOM  {i:>5d}  CA  {_three_letter(aa)} A{i:>4d}    "
            f"{x:8.3f}   0.000   0.000  1.00 20.00           C"
        )
    # Stub zinc cofactor a few angstroms from the start of the chain.
    lines.append(
        "HETATM 9999 ZN    ZN A 999       5.000   2.000   2.000  1.00 20.00          ZN"
    )
    lines.append("END")
    return "\n".join(lines) + "\n"


_ONE_TO_THREE = {
    "A": "ALA", "C": "CYS", "D": "ASP", "E": "GLU", "F": "PHE",
    "G": "GLY", "H": "HIS", "I": "ILE", "K": "LYS", "L": "LEU",
    "M": "MET", "N": "ASN", "P": "PRO", "Q": "GLN", "R": "ARG",
    "S": "SER", "T": "THR", "V": "VAL", "W": "TRP", "Y": "TYR",
}


def _three_letter(aa: str) -> str:
    return _ONE_TO_THREE.get(aa.upper(), "ALA")


# --------------------------- worker entrypoint --------------------------- #

@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    volumes={CACHE_DIR: CACHE_VOLUME},
)
def papercrane_dispatch(
    job_id: str,
    seeds,
    params=None,
    prev_output=None,
) -> dict:
    """Worker-facing NDJSON entrypoint used by `apps/worker/_modalRunner.ts`.

    Emits one `{type:"seed", seed:N, metrics:{...}, artifactKey:"..."}` per
    seed and a final `{type:"done", summary:{...}}`. The worker accumulates
    these into a `ToolOutput`; on any uncaught exception the modal runner
    will mark the seed failed via stderr/exit code.
    """
    seeds = _json_arg(seeds, [])
    params = _json_arg(params, {}) or {}
    prev_output = _json_arg(prev_output, None)

    # Merge `params.toolParams` over top-level params, matching the other
    # adapters (chai1/boltz2/etc.).
    tool_params = (
        params.get("toolParams")
        if isinstance(params.get("toolParams"), dict)
        else {}
    )
    merged: dict = {**params, **tool_params}

    # Pull backbone PDB from prev_output (e.g. an RFdiffusion run upstream)
    # when available, otherwise from the explicit `input_pdb` param.
    internal = merged.get("_papercrane")
    staged_url = (
        internal.get("targetStructureUrl") if isinstance(internal, dict) else None
    )
    input_pdb = (
        staged_url
        or merged.get("input_pdb")
        or merged.get("inputPdb")
        or merged.get("targetPdbText")
        or merged.get("targetPdb")
    )
    if not input_pdb and isinstance(prev_output, dict):
        designs = prev_output.get("designs") or []
        if designs and isinstance(designs[0], dict):
            input_pdb = designs[0].get("structureKey") or designs[0].get("artifactKey")
    if isinstance(input_pdb, str) and input_pdb.startswith(("http://", "https://")):
        import urllib.request

        with urllib.request.urlopen(input_pdb, timeout=120) as response:
            input_pdb = response.read()
    elif isinstance(input_pdb, str) and len(input_pdb.strip()) == 4 and input_pdb.strip().isalnum():
        import urllib.request

        pdb_id = input_pdb.strip().upper()
        with urllib.request.urlopen(
            f"https://files.rcsb.org/download/{pdb_id}.pdb", timeout=120
        ) as response:
            input_pdb = response.read()
    if not input_pdb:
        raise ValueError("LigandMPNN requires a backbone PDB or uploaded target")

    forwarded = {
        "input_pdb": input_pdb,
        "chains_to_design": (
            merged.get("chains_to_design")
            or merged.get("chainsToDesign")
            or merged.get("targetChain")
            or merged.get("chain")
            or "A"
        ),
        "fixed_positions": merged.get("fixed_positions") or merged.get("fixedPositions"),
        "redesigned_residues": merged.get("redesigned_residues") or merged.get("redesignedResidues"),
        "num_seq_per_target": int(merged.get("num_seq_per_target", merged.get("numSeqPerTarget", 1))),
        "temperature": float(merged.get("temperature", 0.1)),
        "omit_aas": str(merged.get("omit_aas", merged.get("omitAAs", "CX"))),
        "ligand_context_radius": float(merged.get("ligand_context_radius", merged.get("ligandContextRadius", 8.0))),
        "model_type": str(merged.get("model_type", merged.get("modelType", "ligand_mpnn"))),
        "checkpoint": merged.get("checkpoint"),
    }

    completed = 0
    for seed in seeds:
        result = _predict_impl(
            job_id=job_id,
            params=forwarded,
            seeds=[int(seed)],
        )
        seed_record = (result.get("seeds") or [{}])[0]
        _emit_event({
            "type": "seed",
            "seed": int(seed),
            "sequence": seed_record.get("best_sequence", ""),
            "artifactKey": seed_record.get("artifactKey", f"jobs/{job_id}/designs/{seed}.fasta"),
            "metrics": _numeric_metrics(seed_record.get("metrics") or {}),
        })
        completed += 1

    summary = {"tool": "ligandmpnn", "completed": completed}
    _emit_event({"type": "done", "summary": summary})
    return summary


# --------------------------- local smoke test --------------------------- #

@app.local_entrypoint()
def main() -> None:
    """Smoke test: design 1 seed against a stub ubiquitin + Zn 'cofactor'."""
    print(
        f"[local] LigandMPNN smoke: len={len(SMOKE_SEQUENCE)} aa, "
        f"seeds=[42], temp=0.1, num_seq=2"
    )
    result = predict.remote(
        job_id="smoke",
        params={
            "chains_to_design": "A",
            "num_seq_per_target": 2,
            "temperature": 0.1,
            "omit_aas": "CX",
            "ligand_context_radius": 8.0,
            "model_type": "ligand_mpnn",
        },
        seeds=[42],
    )
    seeds = result.get("seeds") or []
    print(f"[local] returned {len(seeds)} seed result(s)")
    for s in seeds:
        m = s.get("metrics") or {}
        print(
            f"  seed={s.get('seed')} "
            f"best_seq_len={len(s.get('best_sequence',''))} "
            f"score={m.get('score')} "
            f"global_score={m.get('global_score')} "
            f"recovery={m.get('recovery')} "
            f"artifactKey={s.get('artifactKey')}"
        )
    if not seeds:
        raise SystemExit("FAIL: no seed results returned")
    print("[local] OK")
