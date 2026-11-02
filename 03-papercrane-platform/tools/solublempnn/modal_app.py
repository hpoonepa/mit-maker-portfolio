# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "modal>=1.0",
# ]
# ///
"""Paper Crane SolubleMPNN Modal app.

SolubleMPNN is mechanically identical to ProteinMPNN — same architecture,
same CLI — but loaded with the `soluble_v_48_020.pt` checkpoint, whose
weights were trained on a subset biased toward soluble (non-aggregating,
non-membrane) proteins. This nudges samples away from sticky hydrophobic
patches and toward sequences that express well in E. coli.

Design knobs that matter for solubility (and that this app surfaces in its
metrics):
    - omit_aas: charged residues (H/K/R) and cysteines are common drivers of
      inclusion-body formation; defaulting them out is standard practice
      for soluble design campaigns.
    - temperature: lower = closer to the soluble-biased mode of the
      distribution; strict mode caps at 0.1.
    - predicted_solubility: composite of (1 - fraction_hydrophobic) plus a
      small bonus for balanced charge — a quick smoke metric, NOT a SolubleMPNN
      forward-pass output (the checkpoint just biases sampling, it doesn't emit
      a solubility logit).

Wire contract:
    - Entrypoint `predict(job_id, seeds, params, prev_output)` matches the
      generic `_modalRunner.ts` --json payload shape.
    - Stdout is NDJSON, one event per line, `flush=True` so the worker's
      line-buffered reader picks events up incrementally:
        {"type":"seed", "seed":N, "metrics":{...}, "artifactKey":"..."}
        {"type":"done", "summary":{...}}
        {"type":"error", "code":"...", "message":"...", "retryable":bool}
    - Per-seed FASTA artifacts land at jobs/<jobId>/designs/<seed>.fasta.

Local smoke (no Modal credits expected during dev):
    modal run tools/solublempnn/modal_app.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import modal

# -------------------------- Config -------------------------- #

GPU = os.environ.get("GPU", "A10")  # SolubleMPNN inference is tiny; A10 is plenty.
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", 30))

# SolubleMPNN checkpoint shipped inside the ProteinMPNN repo under
# `soluble_model_weights/`. Match the constant the Python adapter uses so
# any future renames are caught in one place.
SOLUBLE_MODEL_NAME = "soluble_v_48_020"
DEFAULT_OMIT_AAS = "CXHKR"
STRICT_MAX_TEMPERATURE = 0.1

# Pin the ProteinMPNN repo so weight checkpoints + CLI flags stay reproducible.
# Update along with `tools/solublempnn/Dockerfile`'s SOLUBLEMPNN_SHA.
# Last commit on dauparas/ProteinMPNN main as of 2026-06-02 (commit date
# 2023-06-27: "updating solubleMPNN weights trained with a larger set of
# excluded membrane proteins"). Verified via
# `gh api repos/dauparas/ProteinMPNN/commits/main`. SolubleMPNN weights live
# inside this repo under `soluble_model_weights/`.
PROTEINMPNN_REPO = "https://github.com/dauparas/ProteinMPNN.git"
PROTEINMPNN_SHA = "8907e6671bfbfc92303b5f79c4b5e6ce47cdef57"

CACHE_VOLUME_NAME = "papercrane-solublempnn-cache"
CACHE_VOLUME = modal.Volume.from_name(CACHE_VOLUME_NAME, create_if_missing=True)
CACHE_DIR = f"/{CACHE_VOLUME_NAME}"

# Path inside the image where we clone ProteinMPNN. The soluble weights live
# under `${REPO}/soluble_model_weights/<MODEL>.pt`.
REPO_DIR = "/opt/solublempnn"
SOLUBLE_WEIGHTS_DIR = f"{REPO_DIR}/soluble_model_weights"


def _warm_cache() -> None:
    """Copy the SolubleMPNN checkpoint into the persistent volume.

    The weights themselves ship inside the cloned repo, so the "cache" here
    is just a copy that lets us mount-and-go on cold starts without re-cloning.
    """
    import shutil

    cache_root = Path(CACHE_DIR)
    cache_root.mkdir(parents=True, exist_ok=True)
    src = Path(SOLUBLE_WEIGHTS_DIR) / f"{SOLUBLE_MODEL_NAME}.pt"
    dst = cache_root / f"{SOLUBLE_MODEL_NAME}.pt"
    if src.exists() and not dst.exists():
        print(f"Caching {src} -> {dst}")
        shutil.copy2(src, dst)
    else:
        print(f"Cache already populated or weights missing: {src} -> {dst}")


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "wget", "build-essential")
    .pip_install(
        # Torch 2.4.x has wheels matching the CUDA 12.1 base used elsewhere
        # in the papercrane stack; SolubleMPNN's CPU-fallback also works
        # here for the A10 inference path.
        "torch==2.4.1",
        "numpy==1.26.4",
    )
    .run_commands(
        f"git clone {PROTEINMPNN_REPO} {REPO_DIR}",
        f"cd {REPO_DIR} && git checkout {PROTEINMPNN_SHA}",
    )
    .run_function(
        _warm_cache,
        volumes={CACHE_DIR: CACHE_VOLUME},
    )
)

app = modal.App("solublempnn", image=image)


# -------------------------- Helpers -------------------------- #


def _emit_event(event: dict) -> None:
    """One NDJSON line per event, flushed so the worker reader sees it live."""
    print(json.dumps(event), flush=True)


def _json_arg(value, fallback):
    """Tolerate either a JSON string (CLI path) or an already-parsed value."""
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


# Hydrophobic + charged residue partitioning used for our solubility metrics.
# These follow the conventional Kyte-Doolittle partitioning collapsed to a
# binary hydrophobic set, plus the standard charged-at-pH-7 set.
_HYDROPHOBIC_AAS = set("AVILMFWYC")
_CHARGED_AAS = set("DEKRH")
_POSITIVE_AAS = set("KRH")
_NEGATIVE_AAS = set("DE")


def _solubility_metrics(seq: str) -> dict:
    """Cheap, deterministic solubility heuristics for the emitted metrics.

    SolubleMPNN's checkpoint already biases sampling — these are descriptive
    metrics so downstream filters can rank designs without an extra forward
    pass. predicted_solubility is a 0..1 heuristic: higher when the sequence
    has fewer hydrophobic residues and roughly balanced charge.
    """
    if not seq:
        return {
            "sequence_length": 0,
            "fraction_hydrophobic": 0.0,
            "fraction_charged": 0.0,
            "fraction_positive": 0.0,
            "fraction_negative": 0.0,
            "net_charge": 0.0,
            "predicted_solubility": 0.0,
        }
    n = len(seq)
    n_hydro = sum(1 for c in seq if c in _HYDROPHOBIC_AAS)
    n_pos = sum(1 for c in seq if c in _POSITIVE_AAS)
    n_neg = sum(1 for c in seq if c in _NEGATIVE_AAS)
    n_charged = n_pos + n_neg
    frac_hydro = n_hydro / n
    frac_charged = n_charged / n
    frac_pos = n_pos / n
    frac_neg = n_neg / n
    net_charge = float(n_pos - n_neg)
    # Penalize hydrophobicity, lightly reward charge balance.
    charge_balance = 1.0 - (abs(n_pos - n_neg) / max(n_charged, 1))
    predicted_solubility = max(
        0.0,
        min(1.0, 0.7 * (1.0 - frac_hydro) + 0.3 * charge_balance),
    )
    return {
        "sequence_length": n,
        "fraction_hydrophobic": round(frac_hydro, 4),
        "fraction_charged": round(frac_charged, 4),
        "fraction_positive": round(frac_pos, 4),
        "fraction_negative": round(frac_neg, 4),
        "net_charge": net_charge,
        "predicted_solubility": round(predicted_solubility, 4),
    }


# ProteinMPNN FASTA headers look like:
#   >T0, score=1.234, global_score=1.111, fixed_chains=[...], designed_chains=...
# This regex pulls out the float-valued kv pairs (we ignore list-valued ones).
import re as _re  # noqa: E402

_FASTA_KV = _re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([-0-9.eE+]+)")


def _parse_fasta_records(fasta_text: str) -> list[dict]:
    """Return [{header, sequence, kv}, ...] for every record in a FASTA."""
    records: list[dict] = []
    header: str | None = None
    buf: list[str] = []
    for raw in fasta_text.splitlines():
        if raw.startswith(">"):
            if header is not None:
                records.append({
                    "header": header,
                    "sequence": "".join(buf).strip().upper(),
                    "kv": {m.group(1): float(m.group(2)) for m in _FASTA_KV.finditer(header)},
                })
            header = raw[1:]
            buf = []
        else:
            buf.append(raw.strip())
    if header is not None:
        records.append({
            "header": header,
            "sequence": "".join(buf).strip().upper(),
            "kv": {m.group(1): float(m.group(2)) for m in _FASTA_KV.finditer(header)},
        })
    return records


def _stage_backbones(pdb_paths: list[str], stage_dir: Path) -> list[Path]:
    """Copy/write backbones into a flat dir SolubleMPNN can scan.

    Accepts either:
      - absolute paths to existing PDB files (mounted by the caller), or
      - "raw://<filename>:<pdb_text>" inline payloads (used by smoke tests
        that don't want to mount a volume just to design one backbone).
    """
    import shutil
    import urllib.request

    stage_dir.mkdir(parents=True, exist_ok=True)
    staged: list[Path] = []
    for i, p in enumerate(pdb_paths):
        if isinstance(p, str) and p.startswith("raw://"):
            # raw://<name>:<text>
            rest = p[len("raw://") :]
            name, _, text = rest.partition(":")
            dst = stage_dir / (name or f"backbone_{i:04d}.pdb")
            dst.write_text(text)
            staged.append(dst)
        elif isinstance(p, str) and p.lstrip().startswith(
            ("HEADER", "ATOM", "HETATM", "MODEL", "REMARK")
        ):
            dst = stage_dir / f"backbone_{i:04d}.pdb"
            dst.write_text(p)
            staged.append(dst)
        elif isinstance(p, str) and p.startswith(("http://", "https://")):
            dst = stage_dir / f"backbone_{i:04d}.pdb"
            with urllib.request.urlopen(p, timeout=120) as response:
                dst.write_bytes(response.read())
            staged.append(dst)
        elif isinstance(p, str) and len(p.strip()) == 4 and p.strip().isalnum():
            dst = stage_dir / f"{p.strip().upper()}.pdb"
            url = f"https://files.rcsb.org/download/{p.strip().upper()}.pdb"
            with urllib.request.urlopen(url, timeout=120) as response:
                dst.write_bytes(response.read())
            staged.append(dst)
        else:
            src = Path(p)
            if not src.exists():
                raise FileNotFoundError(f"backbone not found: {src}")
            dst = stage_dir / src.name
            shutil.copy2(src, dst)
            staged.append(dst)
    return staged


# -------------------------- Core inference -------------------------- #


def _run_solublempnn(
    pdb_dir: Path,
    out_dir: Path,
    seed: int,
    num_seq_per_target: int,
    sampling_temp: float,
    omit_aas: str,
    chains_to_design: str | None,
    fixed_positions_jsonl: str | None,
) -> int:
    """Invoke the bundled ProteinMPNN CLI with the soluble checkpoint.

    The repo exposes `protein_mpnn_run.py` as a single-shot CLI; we point
    --path_to_model_weights at the mounted cache volume so cold starts don't
    re-clone or re-download.
    """
    from subprocess import run

    cmd = [
        sys.executable,
        f"{REPO_DIR}/protein_mpnn_run.py",
        "--pdb_path", str(pdb_dir),
        "--out_folder", str(out_dir),
        "--num_seq_per_target", str(num_seq_per_target),
        "--sampling_temp", str(sampling_temp),
        "--omit_AAs", omit_aas,
        "--seed", str(seed),
        "--batch_size", "1",
        "--model_name", SOLUBLE_MODEL_NAME,
        "--path_to_model_weights", CACHE_DIR,
    ]
    if chains_to_design:
        cmd += ["--chain_id_jsonl", ""]  # placeholder; chains via CLI flag below
        cmd += ["--pdb_path_chains", chains_to_design]
    if fixed_positions_jsonl:
        cmd += ["--fixed_positions_jsonl", fixed_positions_jsonl]
    print("Running:", " ".join(cmd), flush=True)
    res = run(cmd, check=False)
    return res.returncode


def _collect_designs(out_dir: Path) -> list[dict]:
    """ProteinMPNN drops sequences under `out_dir/seqs/<input_stem>.fa`."""
    records: list[dict] = []
    seqs_dir = out_dir / "seqs"
    if not seqs_dir.exists():
        return records
    for fasta in sorted(seqs_dir.glob("*.fa")):
        records.extend(_parse_fasta_records(fasta.read_text()))
    return records


def _apply_strictness(
    omit_aas: str,
    temperature: float,
    strictness: str,
) -> tuple[str, float]:
    """In strict mode, force the soluble omit set and clamp temperature.

    We deliberately *union* the user-supplied omit list with the defaults so
    a campaign that already excludes additional letters keeps those, but a
    campaign that loosened the defaults gets them re-added.
    """
    if strictness == "strict":
        omit_set = set(omit_aas or "") | set(DEFAULT_OMIT_AAS)
        omit_aas = "".join(sorted(omit_set))
        if temperature > STRICT_MAX_TEMPERATURE:
            temperature = STRICT_MAX_TEMPERATURE
    return omit_aas or DEFAULT_OMIT_AAS, float(temperature)


# Tiny 1-residue PDB stub used as a built-in smoke backbone when callers don't
# provide one. Glycine alpha-carbon only — enough for SolubleMPNN to parse and
# emit a length-1 sequence without us depending on a mounted fixture.
SMOKE_PDB = (
    "HEADER    SMOKE TEST                              01-JAN-26   SMOK\n"
    "ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00 20.00           N  \n"
    "ATOM      2  CA  GLY A   1       1.458   0.000   0.000  1.00 20.00           C  \n"
    "ATOM      3  C   GLY A   1       2.009   1.420   0.000  1.00 20.00           C  \n"
    "ATOM      4  O   GLY A   1       1.251   2.390   0.000  1.00 20.00           O  \n"
    "END\n"
)


# -------------------------- Entrypoints -------------------------- #


@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    volumes={CACHE_DIR: CACHE_VOLUME},
)
def predict(
    job_id: str | None = None,
    seeds=None,
    params=None,
    prev_output=None,
) -> dict:
    """Generic-entrypoint shim used by `_modalRunner.ts` (non-papercrane_dispatch slugs).

    Receives the canonical worker payload:
        --json '{"job_id":"j_123","seeds":[1,2],"params":{...},"prev_output":...}'
    Emits one NDJSON `seed` event per (backbone × seed × num_seq_per_target)
    design, plus a trailing `done` summary. Returns the same summary so callers
    that prefer the function return value (e.g. local entrypoint smoke tests)
    don't have to scrape stdout.
    """
    seeds = _json_arg(seeds, []) or []
    params = _json_arg(params, {}) or {}
    prev_output = _json_arg(prev_output, None)
    job_id = str(job_id or params.get("jobId") or params.get("job_id") or "smoke")

    tool_params = params.get("toolParams") if isinstance(params.get("toolParams"), dict) else {}
    merged: dict = {**params, **(tool_params or {})}

    backbones: list[str] = list(merged.get("backbones") or [])
    if not backbones:
        internal = merged.get("_papercrane")
        staged_url = (
            internal.get("targetStructureUrl") if isinstance(internal, dict) else None
        )
        single = (
            staged_url
            or merged.get("input_pdb")
            or merged.get("inputPdb")
            or merged.get("targetPdbText")
            or merged.get("targetPdb")
        )
        if single:
            backbones = [single]
    if not backbones:
        raise ValueError("SolubleMPNN requires a backbone PDB or uploaded target")

    chains_to_design = (
        merged.get("chains_to_design")
        or merged.get("chainsToDesign")
        or merged.get("targetChain")
        or merged.get("chain")
    )
    fixed_positions = merged.get("fixed_positions") or merged.get("fixedPositions")
    num_seq_per_target = int(merged.get("num_seq_per_target", merged.get("numSeqPerTarget", 1)))
    raw_temperature = float(merged.get("temperature", 0.1))
    raw_omit_aas = str(merged.get("omit_aas", merged.get("omitAas", DEFAULT_OMIT_AAS)))
    # `solubility_weight` is exposed in our predict() params for parity with
    # other MPNN variants; SolubleMPNN doesn't take a weighting scalar at
    # inference time (the checkpoint *is* the bias), so we surface it as a
    # strictness toggle: >= 1.0 maps to strict, otherwise default.
    solubility_weight = float(merged.get("solubility_weight", merged.get("solubilityWeight", 0.0)))
    strictness = str(
        merged.get("solubility_strictness")
        or merged.get("solubilityStrictness")
        or ("strict" if solubility_weight >= 1.0 else "default")
    )
    omit_aas, temperature = _apply_strictness(raw_omit_aas, raw_temperature, strictness)

    if not seeds:
        seeds = [int(merged.get("seed", 42))]

    completed = 0
    errors = 0
    summary: dict = {
        "tool": "solublempnn",
        "model_name": SOLUBLE_MODEL_NAME,
        "strictness": strictness,
        "temperature": temperature,
        "omit_aas": omit_aas,
    }

    try:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as scratch:
            scratch_dir = Path(scratch)
            pdb_dir = scratch_dir / "pdbs"
            staged = _stage_backbones(backbones, pdb_dir)
            print(f"Staged {len(staged)} backbone(s) at {pdb_dir}", flush=True)

            fixed_jsonl: str | None = None
            if fixed_positions:
                fp_path = scratch_dir / "fixed_positions.jsonl"
                fp_path.write_text(json.dumps(fixed_positions))
                fixed_jsonl = str(fp_path)

            for seed in seeds:
                seed_int = int(seed)
                seed_out = scratch_dir / f"out_seed_{seed_int}"
                seed_out.mkdir(parents=True, exist_ok=True)

                try:
                    rc = _run_solublempnn(
                        pdb_dir=pdb_dir,
                        out_dir=seed_out,
                        seed=seed_int,
                        num_seq_per_target=num_seq_per_target,
                        sampling_temp=temperature,
                        omit_aas=omit_aas,
                        chains_to_design=chains_to_design,
                        fixed_positions_jsonl=fixed_jsonl,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    errors += 1
                    _emit_event({
                        "type": "error",
                        "code": "RUN_FAILED",
                        "message": f"seed {seed_int}: {type(exc).__name__}: {exc}",
                        "retryable": True,
                    })
                    continue

                if rc != 0:
                    errors += 1
                    _emit_event({
                        "type": "error",
                        "code": "NONZERO_EXIT",
                        "message": f"SolubleMPNN CLI exited with {rc} for seed {seed_int}",
                        "retryable": True,
                    })
                    continue

                designs = _collect_designs(seed_out)
                # ProteinMPNN's first record is the *input* sequence with
                # score for reference; design samples follow. Skip the first
                # if its header starts with the input tag and there is more
                # than one record.
                if len(designs) > 1 and designs[0]["header"].startswith("T="):
                    designs = designs[1:]
                # Build a combined FASTA artifact for the seed.
                fasta_lines: list[str] = []
                top_metrics: dict = {}
                for idx, rec in enumerate(designs):
                    fasta_lines.append(f">{rec['header']}")
                    fasta_lines.append(rec["sequence"])
                    if idx == 0:
                        # The first sampled design is the canonical one we
                        # surface in the seed event's metrics.
                        sol = _solubility_metrics(rec["sequence"])
                        kv = rec["kv"]
                        top_metrics = {
                            "sample_perplexity": float(kv.get("score", 0.0)),
                            "global_score": float(kv.get("global_score", 0.0)),
                            "seq_recovery": float(kv.get("seq_recovery", 0.0)),
                            **sol,
                        }
                fasta_blob = ("\n".join(fasta_lines) + "\n").encode("utf-8") if fasta_lines else b""

                artifact_key = f"jobs/{job_id}/designs/{seed_int}.fasta"
                _emit_event({
                    "type": "seed",
                    "seed": seed_int,
                    "sequence": (designs[0]["sequence"] if designs else None),
                    "metrics": top_metrics,
                    "artifactKey": artifact_key,
                    "designCount": len(designs),
                    # base64 fasta is omitted from the NDJSON event to keep
                    # stdout small; the worker is expected to mount the
                    # papercrane storage layer for artifact persistence. We
                    # still return the bytes from the function value for the
                    # local entrypoint smoke test.
                })
                completed += 1
    except Exception as exc:  # pragma: no cover - last-ditch surface
        _emit_event({
            "type": "error",
            "code": "DISPATCH_FAILED",
            "message": f"{type(exc).__name__}: {exc}",
            "retryable": False,
        })
        raise

    summary.update({
        "completed": completed,
        "errors": errors,
        "requested": len(seeds),
        "num_seq_per_target": num_seq_per_target,
    })
    _emit_event({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    """Smoke test that exercises the dispatch path without external inputs."""
    payload = {
        "job_id": "smoke-job",
        "seeds": [1, 2],
        "params": {
            "input_pdb": f"raw://smoke.pdb:{SMOKE_PDB}",
            "num_seq_per_target": 1,
            "temperature": 0.1,
            "omit_aas": DEFAULT_OMIT_AAS,
            "solubility_strictness": "default",
        },
    }
    print(f"[local] dispatching SolubleMPNN smoke: seeds={payload['seeds']}")
    result = predict.remote(
        job_id=payload["job_id"],
        seeds=json.dumps(payload["seeds"]),
        params=json.dumps(payload["params"]),
    )
    print(f"[local] summary={json.dumps(result)}")
    if result.get("completed", 0) < 1:
        raise SystemExit("FAIL: no seeds completed")
    print("[local] OK")
