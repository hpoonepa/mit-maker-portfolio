# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "modal>=1.0",
# ]
# ///
"""BindCraft Modal app for Paper Crane.

Headline binder-design tool. Wraps the upstream BindCraft pipeline
(Pacesa et al., https://github.com/martinpacesa/BindCraft) — a hallucination
loop that drives ColabDesign/AF2 backwards through a binder template, scores
each trajectory with PyRosetta + ColabDesign filters, then runs an MPNN
re-design + AF2 validation pass on each accepted trajectory. BindCraft is
deliberately ONE shot per "design": one seed in => one trajectory + its
MPNN children + their AF2 scores. We accumulate accepted designs across
trajectories until `number_of_final_designs` are reached OR
`max_trajectories` are spent.

The image build is ported (verbatim, with version pins) from
`biomodals/modal_bindcraft.py` — that recipe has been run on Modal in
production and is the only known-good path through the BindCraft +
ColabDesign + PyRosetta + JAX-CUDA dependency hell.

Two entrypoints:
- `predict`  : `--json '<payload>'` shape used by `apps/worker/.../_modalRunner.ts`
               (slug `bindcraft` is NOT in PAPERCRANE_ENTRYPOINTS, so the
               runner passes the canonical payload as a single `--json` arg).
- `papercrane_dispatch` : `--job-id / --seeds / --params / --prev-output` shape
               used by alphafold3/boltz2/chai1 today. Wired up now so we can
               promote bindcraft to PAPERCRANE_ENTRYPOINTS without touching
               this file.

Both emit identical NDJSON to stdout, one line per event:
  {"type":"log",   "level":"info", "message":"..."}
  {"type":"seed",  "seed":N, "metrics":{...}, "artifactKey":"...", "sequence":"..."}
  {"type":"done",  "summary":{...}}
  {"type":"error", "code":"...", "message":"...", "retryable":bool}

Run:  modal run tools/bindcraft/modal_app.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import modal

# 50 designs * ~140s/design + JIT compile + AF2 weights I/O + buffer.
# Upstream notes 1h for 3 designs on A100 because BindCraft burns many
# rejected trajectories per accepted design — the 30-min ceiling here is
# tuned for the typical Paper Crane "smoke" job (1-3 designs); larger
# campaigns should override GPU/TIMEOUT via env when invoking.
GPU = os.environ.get("GPU", "A100-40GB")
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", 30))

# Persistent volume for the AlphaFold2 weight tar (~5.3 GB after extract).
# The image bakes weights into `/root/bindcraft/params` at build time, but the
# volume gives us a place to drop user-supplied target PDBs and accumulated
# design output across runs (handy for the worker rsync layer).
BINDCRAFT_VOLUME_NAME = "papercrane-bindcraft-cache"
BINDCRAFT_VOLUME = modal.Volume.from_name(BINDCRAFT_VOLUME_NAME, create_if_missing=True)
CACHE_DIR = f"/{BINDCRAFT_VOLUME_NAME}"

# Pinned upstream SHA — copied from biomodals/modal_bindcraft.py which is the
# only known-good BindCraft revision against the ColabDesign HEAD + JAX <0.7.0
# pin below. Bump in lockstep with the pyrosetta / numpy / jax pins.
BINDCRAFT_SHA = "c0a48d595d4976694aa979438712ac94c16620bb"


def _set_up_pyrosetta() -> None:
    """Install PyRosetta via the official installer (academic-license tarball)."""
    import pyrosetta_installer  # type: ignore

    pyrosetta_installer.install_pyrosetta()


# Image recipe is a port of biomodals/modal_bindcraft.py:
# - python 3.11 because pyrosetta wheels lag the latest CPython
# - numpy<2.0 pinned BEFORE anything else (BindCraft and PyRosetta both
#   refuse to load on numpy 2.x)
# - ColabDesign installed from git HEAD (BindCraft tracks main upstream)
# - alphafold params tarball downloaded with aria2 (multi-connection, far
#   faster than pip/wget for the 5+ GB tarball)
# - JAX pinned <0.7.0 because 0.7.0 removed `jax.tree_util.wraps` which
#   BindCraft + ColabDesign both still use.
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "wget", "aria2", "ffmpeg", "build-essential")
    .pip_install("numpy<2.0")
    .pip_install(
        "pdb-tools==2.4.8",
        "ffmpeg-python==0.2.0",
        "plotly==5.18.0",
        "kaleido==0.2.1",
        "biopython==1.83",
    )
    .pip_install("git+https://github.com/sokrypton/ColabDesign.git")
    .pip_install("pyrosetta-installer")
    .run_commands(
        f"git clone https://github.com/martinpacesa/BindCraft /root/bindcraft",
        f"cd /root/bindcraft && git checkout {BINDCRAFT_SHA}",
        # BindCraft ships two precompiled binaries that need to be executable.
        "chmod +x /root/bindcraft/functions/dssp",
        "chmod +x /root/bindcraft/functions/DAlphaBall.gcc",
        # PyRosetta 2026 removed the implicit str -> DockingPartners
        # conversion used by this pinned BindCraft revision. Apply the
        # equivalent explicit conversion documented by PyRosetta.
        "sed -i '/from pyrosetta.rosetta.core.io import pose_from_pose/a "
        "from pyrosetta.rosetta.core.pose import DockingPartners' "
        "/root/bindcraft/functions/pyrosetta_utils.py",
        "sed -i 's/iam.set_interface(\"A_B\")/"
        "iam.set_interface(DockingPartners.docking_partners_from_string(\"A_B\"))/' "
        "/root/bindcraft/functions/pyrosetta_utils.py",
    )
    .run_commands(
        # ColabDesign needs to be importable as a top-level `colabdesign`
        # package; the pip install drops it under site-packages but BindCraft
        # also looks for it relative to its CWD.
        "ln -s /usr/local/lib/python3.*/dist-packages/colabdesign /colabdesign || true",
        "mkdir -p /params",
    )
    .run_commands(
        # AF2 weights (~5 GB tarball). aria2 with -x 16 saturates Modal's
        # network; raw wget tops out around 30 MB/s, this hits 200+.
        "aria2c -q -x 16 https://storage.googleapis.com/alphafold/alphafold_params_2022-12-06.tar"
        " && mkdir -p /root/bindcraft/params"
        " && tar -xf alphafold_params_2022-12-06.tar -C /root/bindcraft/params"
        " && rm alphafold_params_2022-12-06.tar",
    )
    .run_function(_set_up_pyrosetta)
    .pip_install(
        # Re-pin AFTER pyrosetta runs — pyrosetta-installer may bump numpy.
        "numpy<2.0",
        "jax[cuda]<0.7.0",
        "matplotlib==3.8.1",  # Upstream issue #4: newer matplotlib breaks plots.
    )
)

app = modal.App("papercrane-bindcraft", image=image)


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
    strip anything non-numeric (BindCraft logs nest strings/Nones/arrays)."""
    out: dict = {}
    for k, v in (metrics or {}).items():
        if isinstance(v, bool):
            continue  # bools are technically int in Python; skip them.
        if isinstance(v, (int, float)):
            out[str(k)] = float(v)
    return out


def _upload_structure(merged: dict, seed: int, pdb_path: Path) -> str:
    """Convert an accepted BindCraft PDB to mmCIF and upload it to R2."""
    import urllib.request
    from Bio.PDB import MMCIFIO, PDBParser

    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/bindcraft/{seed}.cif"
        raise RuntimeError("Papercrane artifact upload record is missing")
    if not pdb_path.is_file():
        raise RuntimeError(f"BindCraft output PDB is missing: {pdb_path}")

    structure = PDBParser(QUIET=True).get_structure("bindcraft", str(pdb_path))
    with tempfile.NamedTemporaryFile(suffix=".cif") as handle:
        writer = MMCIFIO()
        writer.set_structure(structure)
        writer.save(handle.name)
        content = Path(handle.name).read_bytes()
    request = urllib.request.Request(
        str(record["url"]),
        data=content,
        method="PUT",
        headers={"Content-Type": str(record.get("contentType") or "chemical/x-cif")},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"artifact upload failed with status {response.status}")
    return str(record["key"])


class BindCraftRunError(RuntimeError):
    """The upstream process started but exited before completing a seed."""


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
    """Return (pdb_string, binder_name).

    Accepted param keys (in order of precedence):
      - target_pdb_str / targetPdbStr  : raw PDB file content
      - target_pdb_b64 / targetPdbB64  : base64-encoded PDB content
      - target_pdb_url / targetPdbUrl  : HTTP(S) URL to a .pdb file
      - target_pdb / targetPdb         : 4-letter RCSB id, OR local container path
    """
    raw = params.get("target_pdb_str") or params.get("targetPdbStr")
    if raw:
        return str(raw), str(params.get("binder_name") or params.get("binderName") or "binder")

    b64 = params.get("target_pdb_b64") or params.get("targetPdbB64")
    if b64:
        import base64
        return base64.b64decode(b64).decode("utf-8"), str(
            params.get("binder_name") or params.get("binderName") or "binder"
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
# BindCraft normalization helpers                                    #
# ------------------------------------------------------------------ #

def _normalize_hotspots(value) -> str:
    """Paper Crane's adapter passes hotspots as a list of
    `{"chain": "A", "resi": 123}` dicts (see adapter.py) or a list of strings
    like ["A123", "A145"]. BindCraft wants a single comma-separated string:
    "A123,A145" or "A123-145,B10-20" or "" (auto-select)."""
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


def _normalize_lengths(params: dict) -> list[int]:
    """BindCraft wants `lengths` as [min, max] (or a longer set the design
    loop samples from). Accepts:
      - binder_length_range: [60, 150]   (manifest default)
      - binder_length: 80                (single value -> [80,80])
      - lengths: [50, 130]               (passthrough)
    """
    rng = (
        params.get("binder_length_range")
        or params.get("binderLengthRange")
        or params.get("lengths")
    )
    if isinstance(rng, list) and len(rng) >= 2:
        return [int(rng[0]), int(rng[-1])]
    single = params.get("binder_length") or params.get("binderLength")
    if single is not None:
        return [int(single), int(single)]
    return [60, 150]  # matches manifest.json defaultParams


def _design_protocol(params: dict) -> str:
    """Map adapter `protocol` (fast/default/slow per input schema) to upstream
    design protocol tags. BindCraft only ships three protocols of substance:
    Default (4-stage multimer), Beta-sheet, Peptide. We treat 'fast' and
    'slow' as Default (the speed knob is `max_trajectories`, not protocol)."""
    p = str(params.get("protocol", "default")).lower()
    if p in {"beta", "beta-sheet", "betasheet"}:
        return "Beta-sheet"
    if p == "peptide":
        return "Peptide"
    return "Default"


# ------------------------------------------------------------------ #
# Core BindCraft runner — one call == one seed campaign              #
# ------------------------------------------------------------------ #

def _run_bindcraft_single_seed(
    *,
    job_id: str,
    seed: int,
    target_pdb_str: str,
    binder_name: str,
    chains: str,
    hotspots: str,
    lengths: list[int],
    number_of_final_designs: int,
    design_protocol: str,
    max_trajectories: int | None,
) -> list[dict]:
    """Run BindCraft for one seed; return a list of accepted-design summaries.

    BindCraft's own random sampler is seeded inside the design loop by
    `np.random.randint(...)` — to get reproducible per-seed runs we re-seed
    numpy / python / jax here BEFORE delegating to the upstream pipeline.

    Each call writes outputs to `{CACHE_DIR}/jobs/{job_id}/seed_{seed}/` so
    the worker rsync layer can pick them up after the function returns.

    Returns: list of dicts, one per accepted design, each shaped like
        {
          "design_name": "binder_l85_s12345_mpnn3",
          "sequence":    "MQIFV...",
          "metrics":     {"plddt": 0.91, "iptm": 0.78, "i_pae": 5.2, ...},
          "structure_relpath": "Accepted/Ranked/1_<...>.pdb",
        }
    """
    import random
    import shutil
    import numpy as np

    # Reseed all RNGs BindCraft's inner loop will touch.
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

    # The most portable invocation: shell out to the upstream CLI. BindCraft
    # ships `bindcraft.py` which takes JSON config files. We materialize the
    # three settings files (target / advanced / filters) in our job root and
    # invoke it directly — this matches the biomodals reference and avoids
    # us re-implementing the 800-line trajectory loop here.
    import subprocess

    starting_pdb = job_root / f"{binder_name}.pdb"
    starting_pdb.write_text(target_pdb_str)

    target_settings = {
        "design_path": design_path,
        "binder_name": binder_name,
        "starting_pdb": str(starting_pdb),
        "chains": chains,
        "target_hotspot_residues": hotspots,
        "lengths": list(lengths),
        "number_of_final_designs": int(number_of_final_designs),
    }
    target_settings_path = job_root / "target_settings.json"
    target_settings_path.write_text(json.dumps(target_settings, indent=2))

    # Pick canonical upstream advanced / filter files. These ship in the
    # cloned BindCraft repo under settings_advanced/ and settings_filters/.
    protocol_tag = {
        "Default": "default_4stage_multimer",
        "Beta-sheet": "betasheet_4stage_multimer",
        "Peptide": "peptide_3stage_multimer",
    }[design_protocol]
    advanced_path = f"/root/bindcraft/settings_advanced/{protocol_tag}.json"
    filters_path = "/root/bindcraft/settings_filters/default_filters.json"

    # Patch max_trajectories if caller requested a cap.
    if max_trajectories is not None:
        adv = json.loads(Path(advanced_path).read_text())
        adv["max_trajectories"] = int(max_trajectories)
        patched_adv = job_root / "advanced_settings.json"
        patched_adv.write_text(json.dumps(adv, indent=2))
        advanced_path = str(patched_adv)

    _log(
        f"bindcraft start seed={seed} binder={binder_name} chains={chains} "
        f"hotspots='{hotspots}' lengths={lengths} "
        f"num_designs={number_of_final_designs} protocol={design_protocol} "
        f"max_traj={max_trajectories}"
    )

    cmd = [
        sys.executable, "/root/bindcraft/bindcraft.py",
        "--settings", str(target_settings_path),
        "--filters", filters_path,
        "--advanced", advanced_path,
    ]
    env = dict(os.environ)
    # Force deterministic-ish behavior on the JAX side per seed.
    env["PYTHONHASHSEED"] = str(seed)
    env["XLA_PYTHON_CLIENT_MEM_FRACTION"] = env.get("XLA_PYTHON_CLIENT_MEM_FRACTION", "0.9")
    env["PYTHONPATH"] = (
        "/root/bindcraft"
        if not env.get("PYTHONPATH")
        else f"/root/bindcraft:{env['PYTHONPATH']}"
    )

    proc = subprocess.run(
        cmd,
        cwd="/root/bindcraft",
        env=env,
        capture_output=True,
        text=True,
    )

    # Always persist the raw log; helps debug filter-rejection patterns.
    (job_root / "bindcraft.log").write_text(
        (proc.stdout or "") + ("\n--- stderr ---\n" + (proc.stderr or "") if proc.stderr else "")
    )

    if proc.returncode != 0:
        # An empty accepted-design list can be a valid, fully-computed seed;
        # a non-zero process exit is not. Raise so the dispatcher does not
        # count infrastructure/runtime failures as completed work.
        raise BindCraftRunError(
            f"bindcraft.py exited {proc.returncode}. "
            f"tail: {(proc.stderr or '')[-400:]}"
        )

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
            # Find the matching ranked structure (rank prefix added by upstream).
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
        BINDCRAFT_VOLUME.commit()
    except Exception:
        # Best-effort; commit() is idempotent and a stale commit is fine.
        pass

    _log(f"seed {seed}: {len(accepted)} accepted design(s)")
    return accepted


def _extract_csv_metrics(row: dict) -> dict:
    """Pull canonical metrics out of BindCraft's final CSV row.

    Upstream column names vary slightly by protocol; we map both the
    Average_ prefix used in `final_design_stats.csv` and the raw column
    names used in `mpnn_design_stats.csv`."""
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
    volumes={CACHE_DIR: BINDCRAFT_VOLUME},
)
def predict(json: str | None = None, **kwargs) -> dict:
    """Worker-facing NDJSON entrypoint.

    `_modalRunner.ts` (the slug `bindcraft` is NOT in PAPERCRANE_ENTRYPOINTS)
    invokes this as:

        modal run tools/bindcraft/modal_app.py::predict --json '<JSON>'

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
    volumes={CACHE_DIR: BINDCRAFT_VOLUME},
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
    _ = _json_arg(prev_output, None)  # accepted but unused: bindcraft is a
                                       # fresh-start binder design tool.
    tool_params = params.get("toolParams") if isinstance(params.get("toolParams"), dict) else {}
    merged = {**params, **tool_params}
    return _dispatch(job_id=str(job_id), seeds=list(seeds), merged=merged)


# ------------------------------------------------------------------ #
# Shared dispatch core                                               #
# ------------------------------------------------------------------ #

def _dispatch(*, job_id: str, seeds: list, merged: dict) -> dict:
    """Per-seed loop shared by both entrypoints.

    The worker normalizes each lane to one requested design, so this emits one
    persisted structure for every successful seed and fails closed when no
    design passes BindCraft's filters.
    """
    try:
        target_pdb_str, binder_name = _resolve_target_pdb(merged)
    except Exception as e:
        _emit({
            "type": "error",
            "code": "TARGET_PDB_RESOLUTION_FAILED",
            "message": f"failed to resolve target PDB: {type(e).__name__}: {e}",
            "retryable": False,
        })
        _emit({"type": "done", "summary": {"tool": "bindcraft", "completed": 0}})
        return {"tool": "bindcraft", "completed": 0, "error": str(e)}

    chains = str(
        merged.get("target_chain")
        or merged.get("targetChain")
        or merged.get("chains")
        or "A"
    )
    hotspots = _normalize_hotspots(merged.get("hotspots") or merged.get("target_hotspot_residues"))
    lengths = _normalize_lengths(merged)
    num_designs = int(
        merged.get("num_designs")
        or merged.get("numDesigns")
        or 1
    )
    protocol = _design_protocol(merged)
    max_trajectories = merged.get("max_trajectories") or merged.get("maxTrajectories")
    if max_trajectories is not None:
        max_trajectories = int(max_trajectories)

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
            accepted = _run_bindcraft_single_seed(
                job_id=job_id,
                seed=seed_int,
                target_pdb_str=target_pdb_str,
                binder_name=binder_name,
                chains=chains,
                hotspots=hotspots,
                lengths=lengths,
                number_of_final_designs=num_designs,
                design_protocol=protocol,
                max_trajectories=max_trajectories,
            )
        except BindCraftRunError as e:
            _emit({
                "type": "error",
                "code": "BINDCRAFT_RUN_FAILED",
                "message": f"seed {seed_int}: {e}",
                "retryable": False,
            })
            continue
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
            _emit({
                "type": "error",
                "code": "NO_DESIGN_PASSED_FILTERS",
                "message": f"seed {seed_int}: BindCraft produced no accepted design",
                "retryable": False,
            })
            continue

        if len(accepted) != 1:
            _emit({
                "type": "error",
                "code": "INVALID_OUTPUT",
                "message": f"seed {seed_int}: BindCraft produced {len(accepted)} designs; expected 1",
                "retryable": False,
            })
            continue

        design = accepted[0]
        structure_relpath = design.get("structure_relpath")
        if not structure_relpath:
            _emit({
                "type": "error",
                "code": "INVALID_OUTPUT",
                "message": f"seed {seed_int}: accepted design has no structure path",
                "retryable": False,
            })
            continue
        output_path = Path(str(structure_relpath))
        if not output_path.is_absolute():
            output_path = Path(CACHE_DIR) / output_path
        artifact_key = _upload_structure(merged, seed_int, output_path)
        accepted_total += 1
        _emit({
            "type": "seed",
            "seed": seed_int,
            "designId": f"{job_id}-s{seed_int}",
            "sequence": design.get("sequence"),
            "artifactKey": artifact_key,
            "structureKey": artifact_key,
            "metrics": _numeric_metrics(design.get("metrics") or {}),
        })

    summary = {
        "tool": "bindcraft",
        "completed": completed,            # seeds that ran without crashing
        "accepted_designs": accepted_total, # designs that passed BindCraft filters
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
    binder_length_min: int = 60,
    binder_length_max: int = 100,
    hotspots: str = "",
    max_trajectories: int | None = 3,
    protocol: str = "default",
) -> None:
    """Smoke test: run BindCraft against a small target with 1 seed, capped
    at 3 trajectories so it finishes inside the default 30-min timeout even
    if every trajectory burns the full ~140s budget.

    Usage:
        modal run tools/bindcraft/modal_app.py
        modal run tools/bindcraft/modal_app.py --target-pdb 1ycr --seeds '[42,43]'
    """
    import secrets

    seed_list = _json_arg(seeds, None)
    if isinstance(seed_list, int):
        seed_list = [seed_list]
    elif not isinstance(seed_list, list):
        seed_list = [int(s) for s in str(seeds).split(",") if s.strip()]

    payload = {
        # Never reuse a prior smoke directory. BindCraft resumes from files in
        # CACHE_DIR, so a fixed id can falsely pass without running a fresh
        # trajectory after an image or dependency change.
        "job_id": f"smoke-{secrets.token_hex(6)}",
        "seeds": seed_list,
        "params": {
            "target_pdb": target_pdb,
            "target_chain": "A",
            "hotspots": hotspots,
            "binder_length_range": [binder_length_min, binder_length_max],
            "num_designs": num_designs,
            "max_trajectories": max_trajectories,
            "protocol": protocol,
        },
    }

    print(f"[local] submitting bindcraft smoke job: target={target_pdb} "
          f"seeds={seed_list} lengths=[{binder_length_min},{binder_length_max}] "
          f"max_traj={max_trajectories}")
    result = predict.remote(json=__import__("json").dumps(payload))
    print(f"[local] summary: {result}")
    if result.get("completed", 0) == 0:
        sys.exit("FAIL: no seeds completed")
    print("[local] OK")
