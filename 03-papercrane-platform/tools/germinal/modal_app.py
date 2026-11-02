# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "modal>=1.0",
# ]
# ///
"""Germinal Modal app for Paper Crane.

De novo epitope-targeted antibody / nanobody design. Wraps the upstream
Germinal pipeline (Mille-Fragoso et al., Stanford / Arc Institute,
https://github.com/SantiagoMille/germinal) — a hallucination + inverse-folding
loop that designs the CDR loops of a VHH (single-domain nanobody) or scFv
framework against a target epitope, then scores each accepted antibody with
AlphaFold-Multimer / AF3 + PyRosetta interface filters.

LICENSE NOTE: Germinal's own code is Apache-2.0 but it depends on IgLM (JHU
non-commercial academic license) and PyRosetta (non-commercial). The effective
license is NON-COMMERCIAL — the manifest flags this with `licenseGate: true`
so the platform gate blocks it from the commercial tier.

Like the other frontier tools the image is a consistent stub (not yet built in
CI); the volume / weights wiring mirrors bindcraft's known-good pattern.

Two entrypoints:
- `predict`  : `--json '<payload>'` shape used by `apps/worker/.../_modalRunner.ts`
               (slug `germinal` is NOT in PAPERCRANE_ENTRYPOINTS, so the runner
               passes the canonical payload as a single `--json` arg).
- `papercrane_dispatch` : `--job-id / --seeds / --params / --prev-output` shape
               used by alphafold3/boltz2/chai1 today. Wired up now so we can
               promote germinal to PAPERCRANE_ENTRYPOINTS without touching this
               file.

Both emit identical NDJSON to stdout, one line per event:
  {"type":"log",   "level":"info", "message":"..."}
  {"type":"seed",  "seed":N, "metrics":{...}, "artifactKey":"...", "sequence":"..."}
  {"type":"done",  "summary":{...}}
  {"type":"error", "code":"...", "message":"...", "retryable":bool}

Run:  modal run tools/germinal/modal_app.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import modal

# Germinal needs 40GB min, 60GB+ recommended — default to the largest GPU class
# available in the catalog. Larger campaigns should override GPU/TIMEOUT via env.
GPU = os.environ.get("GPU", "A100-80GB")
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", 45))

# Persistent volume for the gated weights (AlphaFold-Multimer / AF3 params,
# IgLM, AbLang) and accumulated design output across runs (handy for the
# worker rsync layer).
GERMINAL_VOLUME_NAME = "papercrane-germinal-cache"
GERMINAL_VOLUME = modal.Volume.from_name(GERMINAL_VOLUME_NAME, create_if_missing=True)
CACHE_DIR = f"/{GERMINAL_VOLUME_NAME}"

# Pinned upstream SHA — bump in lockstep with the pyrosetta / numpy / jax pins.
GERMINAL_SHA = "0000000000000000000000000000000000000000"


def _set_up_pyrosetta() -> None:
    """Install PyRosetta via the official installer (non-commercial license)."""
    import pyrosetta_installer  # type: ignore

    pyrosetta_installer.install_pyrosetta()


# Image recipe mirrors bindcraft's known-good binder-design stack and adds the
# antibody-specific dependencies (IgLM non-commercial language model + AbLang).
# This is a consistent stub — the digest in manifest.json is pending the CI
# image build, like every other frontier tool in the catalog.
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "wget", "aria2", "build-essential")
    .pip_install("numpy<2.0")
    .pip_install(
        "iglm",       # JHU non-commercial academic license.
        "ablang",     # antibody language model for framework priors.
        "pdb-tools==2.4.8",
    )
    .pip_install("git+https://github.com/sokrypton/ColabDesign.git")
    .pip_install("pyrosetta-installer")
    .run_commands(
        "git clone https://github.com/SantiagoMille/germinal /root/germinal",
        f"cd /root/germinal && git checkout {GERMINAL_SHA} || true",
        "mkdir -p /params",
    )
    .run_commands(
        # AF-Multimer weights (~5 GB tarball). aria2 with -x 16 saturates
        # Modal's network; raw wget tops out around 30 MB/s, this hits 200+.
        "aria2c -q -x 16 https://storage.googleapis.com/alphafold/alphafold_params_2022-12-06.tar"
        " && mkdir -p /root/germinal/params"
        " && tar -xf alphafold_params_2022-12-06.tar -C /root/germinal/params"
        " && rm alphafold_params_2022-12-06.tar",
    )
    .run_function(_set_up_pyrosetta)
    .pip_install(
        # Re-pin AFTER pyrosetta runs — pyrosetta-installer may bump numpy.
        "numpy<2.0",
        "jax[cuda]<0.7.0",
    )
)

app = modal.App("papercrane-germinal", image=image)


# ------------------------------------------------------------------ #
# NDJSON helpers                                                     #
# ------------------------------------------------------------------ #

def _emit(event: dict) -> None:
    """Write a single NDJSON event to stdout. flush=True is load-bearing —
    the worker reads stdout line-by-line in real time."""
    print(json.dumps(event), flush=True)


def _log(message: str, level: str = "info") -> None:
    _emit({"type": "log", "level": level, "message": message})


def _numeric_metrics(metrics: dict) -> dict:
    """ToolOutput.metrics is typed `Record<string, number>` on the TS side —
    strip anything non-numeric (design logs nest strings/Nones/arrays)."""
    out: dict = {}
    for k, v in (metrics or {}).items():
        if isinstance(v, bool):
            continue  # bools are technically int in Python; skip them.
        if isinstance(v, (int, float)):
            out[str(k)] = float(v)
    return out


def _json_arg(value, fallback):
    """Modal CLI passes everything as strings; decode if needed."""
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


# ------------------------------------------------------------------ #
# Target PDB resolution                                              #
# ------------------------------------------------------------------ #

SMOKE_PDB_ID = "1ycr"  # tiny p53-MDM2, 85aa target, used for smoke tests.


def _fetch_pdb(pdb_id: str) -> str:
    """Pull a PDB file from RCSB. Returns the file as a string."""
    import urllib.request

    url = f"https://files.rcsb.org/download/{pdb_id.upper()}.pdb"
    _log(f"fetching target PDB: {url}")
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8")


def _resolve_target_pdb(params: dict) -> tuple[str, str]:
    """Return (pdb_string, antibody_name).

    Accepted param keys (in order of precedence):
      - target_pdb_str / targetPdbStr  : raw PDB file content
      - target_pdb_b64 / targetPdbB64  : base64-encoded PDB content
      - target_pdb_url / targetPdbUrl  : HTTP(S) URL to a .pdb file
      - target_pdb / targetPdb         : 4-letter RCSB id, OR local container path
    """
    raw = params.get("target_pdb_str") or params.get("targetPdbStr")
    if raw:
        return str(raw), str(params.get("binder_name") or params.get("binderName") or "antibody")

    b64 = params.get("target_pdb_b64") or params.get("targetPdbB64")
    if b64:
        import base64
        return base64.b64decode(b64).decode("utf-8"), str(
            params.get("binder_name") or params.get("binderName") or "antibody"
        )

    url = params.get("target_pdb_url") or params.get("targetPdbUrl")
    if url:
        import urllib.request
        _log(f"fetching target PDB from URL: {url}")
        with urllib.request.urlopen(str(url), timeout=30) as r:
            text = r.read().decode("utf-8")
        return text, str(params.get("binder_name") or params.get("binderName") or Path(str(url)).stem)

    pdb_ref = params.get("target_pdb") or params.get("targetPdb")
    if pdb_ref:
        ref = str(pdb_ref)
        # Local file path inside the container (volume-mounted).
        if "/" in ref and Path(ref).exists():
            return Path(ref).read_text(), str(
                params.get("binder_name") or params.get("binderName") or Path(ref).stem
            )
        # 4-letter PDB id => fetch from RCSB.
        if len(ref) == 4:
            return _fetch_pdb(ref), str(
                params.get("binder_name") or params.get("binderName") or ref.lower()
            )

    # Smoke-test fallback so `modal run` works with no args.
    _log("no target PDB provided; falling back to 1YCR smoke target", level="warn")
    return _fetch_pdb(SMOKE_PDB_ID), "smoke_1ycr"


# ------------------------------------------------------------------ #
# Germinal normalization helpers                                     #
# ------------------------------------------------------------------ #

FRAMEWORK_TYPES = {"VHH", "scFv"}


def _normalize_hotspots(value) -> str:
    """Paper Crane's adapter passes hotspots as a list of
    `{"chain": "A", "resi": 123}` dicts (see adapter.py) or a list of strings
    like ["A123", "A145"]. Germinal wants a single comma-separated string:
    "A123,A145" (auto-select on empty)."""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for h in value:
            if isinstance(h, str):
                parts.append(h)
            elif isinstance(h, dict):
                chain = str(h.get("chain", "A"))
                resi = h.get("resi") if "resi" in h else h.get("residue")
                if resi is not None:
                    parts.append(f"{chain}{resi}")
        return ",".join(parts)
    return str(value)


def _framework_type(params: dict) -> str:
    """Map adapter `frameworkType` (VHH/scFv per input schema) to the upstream
    Germinal framework tag. Defaults to VHH (single-domain nanobody)."""
    ft = str(params.get("frameworkType") or params.get("framework_type") or "VHH")
    if ft not in FRAMEWORK_TYPES:
        _log(f"unknown frameworkType {ft!r}; falling back to VHH", level="warn")
        return "VHH"
    return ft


# ------------------------------------------------------------------ #
# Core Germinal runner — one call == one seed campaign               #
# ------------------------------------------------------------------ #

def _run_germinal_single_seed(
    *,
    job_id: str,
    seed: int,
    target_pdb_str: str,
    antibody_name: str,
    chains: str,
    hotspots: str,
    framework_type: str,
    number_of_final_designs: int,
) -> list[dict]:
    """Run Germinal for one seed; return a list of accepted-design summaries.

    Each call writes outputs to `{CACHE_DIR}/jobs/{job_id}/seed_{seed}/` so the
    worker rsync layer can pick them up after the function returns.

    Returns: list of dicts, one per accepted antibody design, each shaped like
        {
          "design_name": "vhh_s12345_d0",
          "sequence":    "QVQLVESGG...",
          "metrics":     {"plddt": 0.91, "iptm": 0.78, "i_pae": 5.2, ...},
          "structure_relpath": "Accepted/Ranked/1_<...>.pdb",
        }
    """
    import random
    import numpy as np

    # Reseed all RNGs Germinal's inner loop will touch.
    random.seed(seed)
    np.random.seed(seed)
    try:
        import jax  # type: ignore
        _ = jax.random.PRNGKey(seed)  # warms up the JAX runtime, side-effect free
    except Exception:
        pass

    # Stage I/O directories on the volume so artifacts survive worker-side
    # rsync after the function returns.
    job_root = Path(CACHE_DIR) / "jobs" / str(job_id) / f"seed_{int(seed):06d}"
    job_root.mkdir(parents=True, exist_ok=True)
    design_path = str(job_root) + "/"

    accepted: list[dict] = []

    starting_pdb = job_root / f"{antibody_name}.pdb"
    starting_pdb.write_text(target_pdb_str)

    target_settings = {
        "design_path": design_path,
        "antibody_name": antibody_name,
        "starting_pdb": str(starting_pdb),
        "chains": chains,
        "target_hotspot_residues": hotspots,
        "framework_type": framework_type,
        "number_of_final_designs": int(number_of_final_designs),
    }
    target_settings_path = job_root / "target_settings.json"
    target_settings_path.write_text(json.dumps(target_settings, indent=2))

    _log(
        f"germinal start seed={seed} antibody={antibody_name} chains={chains} "
        f"hotspots='{hotspots}' framework={framework_type} "
        f"num_designs={number_of_final_designs}"
    )

    import subprocess

    cmd = [
        "python", "/root/germinal/germinal.py",
        "--settings", str(target_settings_path),
        "--out", design_path,
    ]
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = str(seed)
    env["XLA_PYTHON_CLIENT_MEM_FRACTION"] = env.get("XLA_PYTHON_CLIENT_MEM_FRACTION", "0.9")

    proc = subprocess.run(
        cmd,
        cwd="/root/germinal",
        env=env,
        capture_output=True,
        text=True,
    )

    # Always persist the raw log; helps debug filter-rejection patterns.
    (job_root / "germinal.log").write_text(
        (proc.stdout or "") + ("\n--- stderr ---\n" + (proc.stderr or "") if proc.stderr else "")
    )

    if proc.returncode != 0:
        # Don't raise — emit a structured error event and return empty so the
        # outer loop can continue on the next seed.
        _emit({
            "type": "error",
            "code": "GERMINAL_RUN_FAILED",
            "message": f"seed {seed}: germinal.py exited {proc.returncode}. "
                       f"tail: {(proc.stderr or '')[-400:]}",
            "retryable": False,
        })
        return accepted

    # Parse accepted designs out of the final CSV + Accepted/Ranked/ folder.
    final_csv = Path(design_path) / "final_design_stats.csv"
    accepted_dir = Path(design_path) / "Accepted" / "Ranked"
    if not final_csv.exists():
        _log(f"seed {seed}: no final_design_stats.csv produced "
             "(zero designs passed filters)")
        return accepted

    import csv
    with final_csv.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            design_name = row.get("Design") or row.get("design") or ""
            seq = (row.get("Sequence") or row.get("sequence") or "").strip().upper()
            if not seq:
                continue
            structure_relpath = None
            if accepted_dir.exists():
                for pdb in sorted(accepted_dir.glob(f"*_{design_name}_model*.pdb")):
                    structure_relpath = str(pdb.relative_to(Path(CACHE_DIR)))
                    break
            metrics = _extract_csv_metrics(row)
            accepted.append({
                "design_name": design_name,
                "sequence": seq,
                "metrics": metrics,
                "structure_relpath": structure_relpath,
            })

    # Make sure the volume sees the new files on the host before we return.
    try:
        GERMINAL_VOLUME.commit()
    except Exception:
        # Best-effort; commit() is idempotent and a stale commit is fine.
        pass

    _log(f"seed {seed}: {len(accepted)} accepted design(s)")
    return accepted


def _extract_csv_metrics(row: dict) -> dict:
    """Pull canonical metrics out of Germinal's final CSV row."""
    def _f(*keys: str) -> float | None:
        for k in keys:
            v = row.get(k)
            if v in (None, "", "None"):
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return None

    out: dict = {}
    if (v := _f("Average_pLDDT", "pLDDT", "plddt")) is not None:
        out["plddt"] = v
    if (v := _f("Average_i_pTM", "i_pTM", "iptm")) is not None:
        out["iptm"] = v
    if (v := _f("Average_pTM", "pTM", "ptm")) is not None:
        out["ptm"] = v
    if (v := _f("Average_i_pAE", "i_pAE", "i_pae")) is not None:
        out["i_pae"] = v
    if (v := _f("Average_pAE", "pAE", "pae")) is not None:
        out["pae"] = v
    if (v := _f("Average_dG", "dG")) is not None:
        out["dG"] = v
    if (v := _f("Average_ShapeComplementarity", "ShapeComplementarity")) is not None:
        out["shape_complementarity"] = v
    if (v := _f("Hotspot_RMSD", "Average_Hotspot_RMSD")) is not None:
        out["hotspot_rmsd"] = v
    return out


# ------------------------------------------------------------------ #
# Entrypoint 1: `predict`  (used by `_modalRunner.ts` via --json)    #
# ------------------------------------------------------------------ #

@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    volumes={CACHE_DIR: GERMINAL_VOLUME},
)
def predict(json: str | None = None, **kwargs) -> dict:
    """Worker-facing NDJSON entrypoint.

    `_modalRunner.ts` (the slug `germinal` is NOT in PAPERCRANE_ENTRYPOINTS)
    invokes this as:

        modal run tools/germinal/modal_app.py::predict --json '<JSON>'

    where the JSON payload has shape:
        {
          "job_id":   "<uuid>",
          "seeds":    [1,2,3,...],
          "params":   {...DesignRequest plus toolParams flattened...},
          "prev_output": {...}  // optional, from a previous stage
        }

    Returns a summary dict; the canonical wire format is the NDJSON stream
    on stdout — the worker parses that, the return value is just for the
    `modal run` exit code path.
    """
    payload = _json_arg(json, None) or {}
    if not payload and kwargs:
        # Allow native python invocation (`predict.remote(job_id=..., seeds=...)`).
        payload = {
            "job_id":     kwargs.get("job_id") or kwargs.get("jobId"),
            "seeds":      kwargs.get("seeds") or [],
            "params":     kwargs.get("params") or {},
            "prev_output": kwargs.get("prev_output") or kwargs.get("prevOutput"),
        }

    job_id = str(payload.get("job_id") or payload.get("jobId") or "local")
    seeds = payload.get("seeds") or [42]
    if isinstance(seeds, str):
        seeds = _json_arg(seeds, [42])
    params = payload.get("params") or {}
    if isinstance(params, str):
        params = _json_arg(params, {})
    # toolParams (per adapter.py) may be nested under params.toolParams.
    tool_params = params.get("toolParams") if isinstance(params.get("toolParams"), dict) else {}
    merged = {**params, **tool_params}

    return _dispatch(job_id=job_id, seeds=list(seeds), merged=merged)


# ------------------------------------------------------------------ #
# Entrypoint 2: `papercrane_dispatch`  (forward-compat with chai1/boltz2 shape) #
# ------------------------------------------------------------------ #

@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    volumes={CACHE_DIR: GERMINAL_VOLUME},
)
def papercrane_dispatch(
    job_id: str,
    seeds,
    params=None,
    prev_output=None,
) -> dict:
    """Same as `predict` but in the alphafold3/boltz2/chai1 arg shape so we
    can flip the slug into `_modalRunner.ts::PAPERCRANE_ENTRYPOINTS` later
    without touching this file."""
    seeds = _json_arg(seeds, [])
    params = _json_arg(params, {}) or {}
    _ = _json_arg(prev_output, None)  # accepted but unused: germinal is a
                                       # fresh-start antibody design tool.
    tool_params = params.get("toolParams") if isinstance(params.get("toolParams"), dict) else {}
    merged = {**params, **tool_params}
    return _dispatch(job_id=str(job_id), seeds=list(seeds), merged=merged)


# ------------------------------------------------------------------ #
# Shared dispatch core                                               #
# ------------------------------------------------------------------ #

def _dispatch(*, job_id: str, seeds: list, merged: dict) -> dict:
    """Per-seed loop shared by both entrypoints. One NDJSON event per accepted
    design (NOT one per seed) so that filter-heavy seeds that accumulate >1
    accepted antibody still surface every design."""
    try:
        target_pdb_str, antibody_name = _resolve_target_pdb(merged)
    except Exception as e:
        _emit({
            "type": "error",
            "code": "TARGET_PDB_RESOLUTION_FAILED",
            "message": f"failed to resolve target PDB: {type(e).__name__}: {e}",
            "retryable": False,
        })
        _emit({"type": "done", "summary": {"tool": "germinal", "completed": 0}})
        return {"tool": "germinal", "completed": 0, "error": str(e)}

    chains = str(
        merged.get("target_chain")
        or merged.get("targetChain")
        or merged.get("chains")
        or "A"
    )
    hotspots = _normalize_hotspots(merged.get("hotspots") or merged.get("target_hotspot_residues"))
    framework_type = _framework_type(merged)
    num_designs = int(
        merged.get("num_designs")
        or merged.get("numDesigns")
        or 1
    )

    if not seeds:
        seeds = [42]

    completed = 0
    accepted_total = 0
    for seed in seeds:
        try:
            seed_int = int(seed)
        except (TypeError, ValueError):
            _emit({
                "type": "error",
                "code": "BAD_SEED",
                "message": f"seed must be int-coercible, got {seed!r}",
                "retryable": False,
            })
            continue

        try:
            accepted = _run_germinal_single_seed(
                job_id=job_id,
                seed=seed_int,
                target_pdb_str=target_pdb_str,
                antibody_name=antibody_name,
                chains=chains,
                hotspots=hotspots,
                framework_type=framework_type,
                number_of_final_designs=num_designs,
            )
        except Exception as e:
            _emit({
                "type": "error",
                "code": "RUNTIME_ERROR",
                "message": f"seed {seed_int}: {type(e).__name__}: {e}",
                "retryable": False,
            })
            continue

        completed += 1

        if not accepted:
            # Still emit a `seed` event so the worker sees per-seed progress
            # even when no design passes filters — metrics={} signals
            # "ran-but-empty" vs the silence of a never-started seed.
            _emit({
                "type": "seed",
                "seed": seed_int,
                "metrics": {},
                "artifactKey": f"jobs/{job_id}/germinal/seed_{seed_int:06d}/",
            })
            continue

        for idx, design in enumerate(accepted):
            accepted_total += 1
            artifact_key = (
                f"jobs/{job_id}/germinal/seed_{seed_int:06d}/"
                f"{design.get('structure_relpath') or f'design_{idx}.pdb'}"
            )
            _emit({
                "type": "seed",
                "seed": seed_int,
                "designId": f"{job_id}-s{seed_int}-d{idx}",
                "sequence": design.get("sequence"),
                "artifactKey": artifact_key,
                "structureKey": artifact_key,
                "metrics": _numeric_metrics(design.get("metrics") or {}),
            })

    summary = {
        "tool": "germinal",
        "completed": completed,            # seeds that ran without crashing
        "accepted_designs": accepted_total, # designs that passed Germinal filters
        "requested_seeds": len(seeds),
    }
    _emit({"type": "done", "summary": summary})
    return summary


# ------------------------------------------------------------------ #
# Local entrypoint — smoke test                                      #
# ------------------------------------------------------------------ #

@app.local_entrypoint()
def main(
    target_pdb: str = SMOKE_PDB_ID,
    seeds: str = "42",
    num_designs: int = 1,
    framework_type: str = "VHH",
    hotspots: str = "",
) -> None:
    """Smoke test: run Germinal against a small target with 1 seed.

    Usage:
        modal run tools/germinal/modal_app.py
        modal run tools/germinal/modal_app.py --target-pdb 1ycr --seeds '[42,43]'
    """
    seed_list = _json_arg(seeds, None)
    if seed_list is None:
        seed_list = [int(s) for s in str(seeds).split(",") if s.strip()]

    payload = {
        "job_id": "smoke-local",
        "seeds": seed_list,
        "params": {
            "target_pdb": target_pdb,
            "target_chain": "A",
            "hotspots": hotspots,
            "frameworkType": framework_type,
            "num_designs": num_designs,
        },
    }

    print(f"[local] submitting germinal smoke job: target={target_pdb} "
          f"seeds={seed_list} framework={framework_type}")
    result = predict.remote(json=__import__("json").dumps(payload))
    print(f"[local] summary: {result}")
    if result.get("completed", 0) == 0:
        sys.exit("FAIL: no seeds completed")
    print("[local] OK")
