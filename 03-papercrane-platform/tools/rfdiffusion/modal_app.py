# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "modal>=1.0",
# ]
# ///
"""Paper Crane RFdiffusion Modal app.

Backbone generator. Pairs with ProteinMPNN downstream for full design pipeline
(see manifest.composes = ["proteinmpnn"]).

RFdiffusion is the brittlest of our tool images:
  - Upstream env.yml pins very old deps (torch 1.9, dgl 1.0.1, e3nn 0.3.3).
  - Ships a vendored SE3-Transformer that requires building against the
    installed torch+CUDA, so we clone at a pinned SHA and install everything in
    a single image layer so a torch version mismatch fails the build, not a run.
  - Weights are NOT on pip — they ship from the Baker lab as ~3 GB of .pt files
    via a public HTTP mirror (http://files.ipd.uw.edu/pub/RFdiffusion/...). We
    cache them in a persistent `papercrane-rfdiff-cache` modal.Volume so the
    image build doesn't repeat the download.

Wire format matches `apps/worker/src/adapters/_modalRunner.ts`:
  - papercrane_dispatch(job_id, seeds, params, prev_output) is the entrypoint
    the worker invokes through `modal run`.
  - Each completed seed emits one NDJSON line to stdout:
        {"type":"seed", "seed":N, "metrics":{...}, "artifactKey":"..."}
  - Terminal event on success:  {"type":"done", "summary":{...}}
  - Terminal event on failure:  {"type":"error", "code":..., "retryable":bool}

Test (do NOT run unless explicitly approved — burns Modal credits):
    modal run tools/rfdiffusion/modal_app.py
"""

from __future__ import annotations

import json
import io
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import modal

# ---------------------------------------------------------------------------
# Config (env-overridable for swarm/CI tuning)
# ---------------------------------------------------------------------------

GPU = os.environ.get("GPU", "A100-40GB")
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", 45))

# Pinned upstream commit. Bump only when re-validating the full image stack.
# Upstream: https://github.com/RosettaCommons/RFdiffusion
# This SHA is 1.1.0 era (Feb 2024) — known-good with the deps we pin below.
RFDIFFUSION_SHA = os.environ.get(
    "RFDIFFUSION_SHA",
    "5606075d45bd23aa60785024b203ed6b0f6d2cd0",
)

# Baker lab public weight mirror.
WEIGHTS_BASE_URL = "http://files.ipd.uw.edu/pub/RFdiffusion"
# The upstream mirror stores each checkpoint below a content-addressed
# directory. Bare ``.../RFdiffusion/Base_ckpt.pt`` URLs return 404.
# Keep these paths aligned with RosettaCommons/RFdiffusion's README.
WEIGHTS_FILES = {
    "Base_ckpt.pt": "6f5902ac237024bdd0c176cb93063dc4",
    "Complex_base_ckpt.pt": "e29311f6f1af907f9ef9f44b8328b",
    "Complex_Fold_base_ckpt.pt": "60f09a193fb5e5ccdc4980417708dbab",
    "Complex_beta_ckpt.pt": "f572d396fae9206628714fb2ce00f72e",
    "ActiveSite_ckpt.pt": "5532d2e1f3a4738decd58b19d633b3c3",
    "InpaintSeq_ckpt.pt": "74f51cfb8b440f50d70878e05361d8f0",
    "InpaintSeq_Fold_ckpt.pt": "76d00716416567174cdb7ca96e208296",
}

# Persistent volume for the ~3 GB of .pt weights. Lives across deploys.
WEIGHTS_VOLUME_NAME = "papercrane-rfdiff-cache"
WEIGHTS_VOLUME = modal.Volume.from_name(WEIGHTS_VOLUME_NAME, create_if_missing=True)
WEIGHTS_DIR = f"/{WEIGHTS_VOLUME_NAME}/models"

# Where the upstream repo lives in the image. Hydra configs are under
# /opt/rfdiffusion/config/inference; scripts/run_inference.py is the entry.
RFDIFF_REPO = "/opt/rfdiffusion"


# ---------------------------------------------------------------------------
# Image build
# ---------------------------------------------------------------------------
#
# Order matters: every layer below is structured so the heaviest steps (the
# torch + DGL + SE3-Transformer build) sit ABOVE rarely-changing layers. Don't
# reorder without re-validating image cache hits.

def _download_weights() -> None:
    """Pull all Baker-lab RFdiffusion weights into the mounted volume.

    Run once at image build (`.run_function(..., volumes=...)`) so the
    runtime hot path never blocks on a 3 GB download. Idempotent: skips
    files already present so volume re-uses cleanly across rebuilds.
    """
    import urllib.request

    target_dir = Path(WEIGHTS_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)

    for fname, content_id in WEIGHTS_FILES.items():
        dst = target_dir / fname
        if dst.exists() and dst.stat().st_size > 1_000_000:
            print(f"[rfdiff-weights] {fname} already cached ({dst.stat().st_size} B)")
            continue
        url = f"{WEIGHTS_BASE_URL}/{content_id}/{fname}"
        tmp = dst.with_suffix(dst.suffix + ".partial")
        print(f"[rfdiff-weights] downloading {url} -> {dst}")
        try:
            urllib.request.urlretrieve(url, tmp)
            tmp.rename(dst)
        except Exception as exc:  # pragma: no cover - network
            print(f"[rfdiff-weights] FAILED {fname}: {exc}")
            if tmp.exists():
                tmp.unlink()
            # Don't raise on optional weights — Base_ckpt.pt is the only hard
            # requirement for the default (unconditional) binder pipeline.
            if fname == "Base_ckpt.pt":
                raise


image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install(
        "git",
        "wget",
        "curl",
        "build-essential",
        # DGL / SE3-Transformer need a working C++ toolchain to build wheels.
        "g++",
        # PyMOL-free PDB IO; rfdiff itself doesn't need pymol but a few
        # helper scripts shell out to obabel.
        "libgl1",
    )
    # Pin CUDA-matching torch FIRST. RFdiffusion's vendored SE3-Transformer is
    # built against whatever torch is present at import time; mixing versions
    # later is the #1 way to brick the image.
    .pip_install(
        "torch==2.1.2",
        "torchvision==0.16.2",
        "torchaudio==2.1.2",
        index_url="https://download.pytorch.org/whl/cu121",
    )
    .pip_install(
        # RFdiffusion env.yml deps. Pin exact versions — newer hydra/omegaconf
        # break the hydra @hydra.main decorator the upstream script uses.
        "hydra-core==1.3.2",
        "omegaconf==2.3.0",
        "icecream==2.1.3",
        # e3nn 0.5.x changed the spherical-harmonics signature; stay on 0.3.x.
        "e3nn==0.3.3",
        # opt_einsum + decorator are e3nn transitive deps we pin to avoid
        # solver drift.
        "opt_einsum==3.3.0",
        "decorator==5.1.1",
        "biopython==1.83",
        # DGL 1.x cu121 wheel for torch 2.1. Upstream env.yml uses 1.0.1 on
        # cu118; 1.1.2-cu121 is the closest binary-compatible release.
        "dgl==1.1.2",
        # SE3-Transformer needs these for the SchNet-like wrappers.
        "scipy==1.11.4",
        "numpy<2",  # numpy 2 breaks dgl 1.1.2 ABI.
    )
    .run_commands(
        # Clone RFdiffusion at the pinned SHA.
        f"git clone https://github.com/RosettaCommons/RFdiffusion.git {RFDIFF_REPO}",
        f"cd {RFDIFF_REPO} && git checkout {RFDIFFUSION_SHA}",
        # Vendored SE3-Transformer ships as a sub-package; install in editable
        # mode so the import path RFdiffusion expects (`SE3Transformer`) is on
        # PYTHONPATH.
        f"cd {RFDIFF_REPO}/env/SE3Transformer && pip install --no-cache-dir .",
        # The repo itself isn't a pip package; expose it via PYTHONPATH at
        # runtime. We append rather than overwrite so anything else mounted at
        # /opt stays importable.
    )
    .env(
        {
            "PYTHONPATH": f"{RFDIFF_REPO}:{RFDIFF_REPO}/env/SE3Transformer",
            # RFdiffusion looks up weights via hydra config var
            # `inference.ckpt_override_path` — but the default config also
            # peeks at a model_directory; setting both is harmless.
            "DGLBACKEND": "pytorch",
            # Quiet hydra working-dir spam in NDJSON output.
            "HYDRA_FULL_ERROR": "1",
        }
    )
    # Pre-populate the weights volume during image build. GPU isn't required
    # for the download itself, but RFdiffusion's first inference call lazy-
    # initialises CUDA kernels, so leave GPU runtime to the predict path.
    .run_function(
        _download_weights,
        volumes={f"/{WEIGHTS_VOLUME_NAME}": WEIGHTS_VOLUME},
    )
)

app = modal.App("papercrane-rfdiffusion", image=image)


# ---------------------------------------------------------------------------
# Smoke fixture — used when no target PDB is supplied by the dispatch caller.
# Ubiquitin chain A (PDB 1UBQ, 76 aa) is the canonical micro-target.
# ---------------------------------------------------------------------------

SMOKE_PDB_ID = "1UBQ"
DEFAULT_TARGET_RANGE = "1-76"  # ubiquitin length; adapter.py uses 1-150 generic.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _emit_event(event: dict) -> None:
    """NDJSON line on stdout. Flushed so the worker streams events live."""
    print(json.dumps(event), flush=True)


def _json_arg(value: Any, fallback: Any) -> Any:
    """Tolerant JSON-or-passthrough decoder for `modal run --json` payloads."""
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _fetch_pdb(pdb_id: str, dest: Path) -> Path:
    """Download a PDB from RCSB. Raises on HTTP failure (no silent fallback)."""
    import urllib.request

    url = f"https://files.rcsb.org/download/{pdb_id.upper()}.pdb"
    print(f"[rfdiff] fetching target PDB: {url}")
    urllib.request.urlretrieve(url, dest)
    return dest


def _build_contigs(
    target_chain: str,
    target_range: str,
    binder_length_range: list[int],
    override: str | None,
) -> str:
    """Compose an RFdiffusion contigmap.contigs string.

    Format: "[A1-150/0 60-150]" = hold chain A residues 1..150 fixed, then
    generate a 60..150-residue binder chain. `override` lets a caller pass any
    contig DSL directly.
    """
    if override and override.strip():
        return override.strip()
    lo, hi = binder_length_range
    return f"[{target_chain}{target_range}/0 {lo}-{hi}]"


def _format_hotspots(hotspots: list[Any], target_chain: str) -> list[str]:
    """Normalise the worker payload's hotspots into RFdiffusion tokens.

    Accepts:
      - ["A33", "A52"]                 -> passthrough
      - [{"chain":"A","resi":33}, ...] -> rendered as "A33"
      - [33, 52]                       -> assume target_chain prefix
    Returns a list like ["A33", "A52"] which hydra renders as a Python list
    when interpolated into the CLI ppi.hotspot_res override.
    """
    out: list[str] = []
    for h in hotspots or []:
        if isinstance(h, str):
            out.append(h)
        elif isinstance(h, dict):
            chain = str(h.get("chain") or target_chain)
            resi = h.get("resi") or h.get("residue") or h.get("position")
            if resi is None:
                continue
            out.append(f"{chain}{int(resi)}")
        elif isinstance(h, int):
            out.append(f"{target_chain}{h}")
    return out


def _count_chain_residues(pdb_path: Path, chain: str | None = None) -> int:
    """Cheap residue counter for plddt fallback metrics."""
    seen: set[tuple[str, str]] = set()
    try:
        for line in pdb_path.read_text().splitlines():
            if line.startswith(("ATOM", "HETATM")):
                c = line[21:22]
                r = line[22:26].strip()
                if chain and c != chain:
                    continue
                if r:
                    seen.add((c, r))
    except OSError:
        return 0
    return len(seen)


def _parse_trb(trb_path: Path) -> dict[str, float]:
    """Best-effort metric extraction from RFdiffusion's .trb trajectory pickle.

    RFdiffusion does NOT emit pLDDT — it's a generative model without a
    confidence head. We surface what IS in the .trb so downstream filters can
    use it:
      - mean_plddt: if present (rare, only certain ckpts)
      - lddt_mean: per-residue lddt average (when complex ckpts used)
    Anything missing returns 0.0 so the metrics dict always has a numeric.

    Robust to missing files / bad pickles — this is metadata, not load-bearing.
    """
    metrics: dict[str, float] = {}
    if not trb_path.exists():
        return metrics
    try:
        import pickle

        with trb_path.open("rb") as f:
            data = pickle.load(f)
        # Field names vary by checkpoint. Probe a few likely ones.
        for key in ("plddt", "mean_plddt", "lddt", "lddt_mean"):
            if key in data:
                arr = data[key]
                try:
                    import numpy as np

                    val = float(np.asarray(arr).mean())
                    metrics[key] = val
                except Exception:
                    pass
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[rfdiff] .trb parse failed for {trb_path.name}: {exc}")
    return metrics


# ---------------------------------------------------------------------------
# Core predict (single-seed)
# ---------------------------------------------------------------------------

@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    cpu=8.0,
    memory=24 * 1024,
    buffer_containers=1,
    scaledown_window=300,
    volumes={f"/{WEIGHTS_VOLUME_NAME}": WEIGHTS_VOLUME},
)
def predict(
    target_pdb: str | None = None,
    target_pdb_id: str | None = None,
    target_chain: str = "A",
    target_range: str = "1-150",
    hotspots: list[Any] | None = None,
    binder_length_range: tuple[int, int] | list[int] = (60, 150),
    num_designs: int = 1,
    contigs: str | None = None,
    inference_steps: int = 50,
    noise_scale: float = 1.0,
    seed: int = 42,
) -> dict:
    """Run RFdiffusion for a single seed and return backbone PDBs in-memory.

    Args:
        target_pdb: Raw PDB text (or filesystem path) of the target. If
            None, falls back to `target_pdb_id` -> RCSB.
        target_pdb_id: 4-char RCSB ID, fetched if `target_pdb` is None.
            Smoke fallback: 1UBQ.
        target_chain: Chain ID of the target residue range.
        target_range: Residue range string for the held-fixed target,
            e.g. "1-150". Used only when `contigs` is None.
        hotspots: Hotspot residues (see _format_hotspots for accepted shapes).
        binder_length_range: (min, max) length of the generated binder.
        num_designs: Backbones per seed (RFdiffusion's inner loop).
        contigs: Full contigmap.contigs override; bypasses target_range +
            binder_length_range when supplied.
        inference_steps: Diffusion denoising steps (default 50, max ~200).
        noise_scale: Both ca/frame noise scales. Lower = more conservative.
        seed: RNG seed.

    Returns:
        dict with keys:
          seed, contigs, num_designs, num_outputs,
          designs: [{design_index, pdb_name, pdb_bytes, metrics, trb_name}]
    """
    return _predict_impl(
        target_pdb=target_pdb,
        target_pdb_id=target_pdb_id,
        target_chain=target_chain,
        target_range=target_range,
        hotspots=hotspots,
        binder_length_range=list(binder_length_range),
        num_designs=num_designs,
        contigs=contigs,
        inference_steps=inference_steps,
        noise_scale=noise_scale,
        seed=seed,
    )


def _predict_impl(
    target_pdb: str | None,
    target_pdb_id: str | None,
    target_chain: str,
    target_range: str,
    hotspots: list[Any] | None,
    binder_length_range: list[int],
    num_designs: int,
    contigs: str | None,
    inference_steps: int,
    noise_scale: float,
    seed: int,
) -> dict:
    """Pure-Python core (separated from the @app.function so it's testable)."""
    from tempfile import TemporaryDirectory

    if binder_length_range and len(binder_length_range) != 2:
        raise ValueError("binder_length_range must be [min, max]")

    contigs_str = _build_contigs(
        target_chain=target_chain,
        target_range=target_range,
        binder_length_range=binder_length_range,
        override=contigs,
    )
    hotspot_tokens = _format_hotspots(hotspots or [], target_chain=target_chain)

    with TemporaryDirectory() as td_in, TemporaryDirectory() as td_out:
        in_dir = Path(td_in)
        out_dir = Path(td_out)

        # ---- materialise target PDB ---------------------------------------
        pdb_path = in_dir / "target.pdb"
        if target_pdb and isinstance(target_pdb, str) and target_pdb.lstrip().startswith(
            ("HEADER", "ATOM", "TITLE", "REMARK", "CRYST1")
        ):
            pdb_path.write_text(target_pdb)
        elif target_pdb and Path(target_pdb).is_file():
            shutil.copy(target_pdb, pdb_path)
        else:
            _fetch_pdb(target_pdb_id or SMOKE_PDB_ID, pdb_path)

        # ---- assemble hydra CLI overrides ---------------------------------
        prefix = out_dir / f"backbone_s{seed}"
        # ckpt_override_path picks Complex_base for hotspot/binder mode.
        # We default to Complex_base when hotspots are supplied (the upstream
        # binder mode recommendation) and Base_ckpt otherwise.
        ckpt_name = "Complex_base_ckpt.pt" if hotspot_tokens else "Base_ckpt.pt"
        ckpt_path = f"{WEIGHTS_DIR}/{ckpt_name}"
        if not Path(ckpt_path).exists():
            # Fallback to Base if a complex ckpt is missing.
            ckpt_path = f"{WEIGHTS_DIR}/Base_ckpt.pt"

        cmd = [
            "python", f"{RFDIFF_REPO}/scripts/run_inference.py",
            f"inference.input_pdb={pdb_path}",
            f"inference.output_prefix={prefix}",
            f"inference.num_designs={int(num_designs)}",
            f"inference.ckpt_override_path={ckpt_path}",
            f"inference.model_directory_path={WEIGHTS_DIR}",
            f"contigmap.contigs={contigs_str}",
            f"diffuser.T={int(inference_steps)}",
            f"denoiser.noise_scale_ca={float(noise_scale)}",
            f"denoiser.noise_scale_frame={float(noise_scale)}",
            f"inference.deterministic=True",
            f"inference.seed={int(seed)}",
        ]
        if hotspot_tokens:
            # Hydra wants Python-list literal: ppi.hotspot_res=[\"A33\",\"A52\"]
            list_literal = "[" + ",".join(f'\\"{h}\\"' for h in hotspot_tokens) + "]"
            cmd.append(f"ppi.hotspot_res={list_literal}")

        print(f"[rfdiff] seed={seed} contigs={contigs_str} ckpt={ckpt_name} "
              f"hotspots={hotspot_tokens} steps={inference_steps}")
        print("[rfdiff] cmd:", " ".join(cmd))

        env = dict(os.environ)
        # Force CUDA visible to subprocess.
        env.setdefault("CUDA_VISIBLE_DEVICES", "0")
        subprocess.run(cmd, check=True, env=env, cwd=RFDIFF_REPO)

        # ---- collect outputs ---------------------------------------------
        designs: list[dict] = []
        # RFdiffusion writes <prefix>_<i>.pdb and <prefix>_<i>.trb.
        pdbs = sorted(out_dir.glob(f"{prefix.name}_*.pdb"))
        for pdb in pdbs:
            try:
                idx = int(pdb.stem.rsplit("_", 1)[1])
            except (IndexError, ValueError):
                idx = 0
            trb = pdb.with_suffix(".trb")
            trb_metrics = _parse_trb(trb)
            # Always include length so downstream filters have a numeric.
            length = float(_count_chain_residues(pdb))
            metrics = {
                "length": length,
                # RFdiffusion has no native pLDDT — surface 0.0 so the metric
                # shape stays stable across tools. ProteinMPNN + a folder
                # (Boltz/Chai) downstream will provide the real confidence.
                "plddt_contig_mean": float(trb_metrics.get("plddt", 0.0)),
                **{f"trb_{k}": v for k, v in trb_metrics.items()},
            }
            designs.append({
                "design_index": idx,
                "pdb_name": pdb.name,
                "pdb_bytes": pdb.read_bytes(),
                "trb_name": trb.name if trb.exists() else None,
                "trb_bytes": trb.read_bytes() if trb.exists() else None,
                "metrics": metrics,
            })

        return {
            "seed": seed,
            "contigs": contigs_str,
            "num_designs": int(num_designs),
            "num_outputs": len(designs),
            "noise_scale": float(noise_scale),
            "hotspots": hotspot_tokens,
            "ckpt": ckpt_name,
            "designs": designs,
        }


# ---------------------------------------------------------------------------
# Worker-facing dispatch (NDJSON stream)
# ---------------------------------------------------------------------------

def _numeric_metrics(metrics: dict) -> dict:
    return {k: v for k, v in metrics.items() if isinstance(v, (int, float))}


def _upload_structure(merged: dict, seed: int, pdb_bytes: bytes) -> str:
    """Convert an RFdiffusion PDB to mmCIF and upload to the owned R2 key."""
    import tempfile
    import urllib.request
    from Bio.PDB import MMCIFIO, PDBParser

    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict) or not record.get("url") or not record.get("key"):
        if os.environ.get("PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS") == "1":
            return f"ephemeral/rfdiffusion/{seed}.cif"
        raise RuntimeError("Papercrane artifact upload record is missing")

    structure = PDBParser(QUIET=True).get_structure(
        "rfdiffusion", io.StringIO(pdb_bytes.decode("utf-8", "replace"))
    )
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


@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    cpu=8.0,
    memory=24 * 1024,
    volumes={f"/{WEIGHTS_VOLUME_NAME}": WEIGHTS_VOLUME},
)
def papercrane_dispatch(
    job_id: str,
    seeds: Any,
    params: Any = None,
    prev_output: Any = None,
) -> dict:
    """Worker-facing NDJSON entrypoint matching `_modalRunner.ts`.

    Reads:
      seeds:  list[int] (or JSON-encoded string)
      params: DesignRequest-shaped dict; we look at both `params.*` and
              `params.toolParams.*` so adapter-level overrides win.

    Each worker lane is normalized to one design per seed and uploads that
    structure to the presigned organization-owned artifact key.

    Terminal events:
      {"type": "done", "summary": {...}}      on success
      {"type": "error", "code", "message", "retryable"}  on failure (and
        re-raises so the modal CLI exits non-zero).
    """
    seeds = _json_arg(seeds, [])
    params = _json_arg(params, {}) or {}
    prev_output = _json_arg(prev_output, None)
    tool_params = (
        params.get("toolParams") if isinstance(params.get("toolParams"), dict) else {}
    ) or {}
    merged = {**params, **tool_params}

    target_pdb = merged.get("targetPdbText") or merged.get("target_pdb_text")
    target_pdb_id = (
        merged.get("targetPdb")
        or merged.get("target_pdb")
        or merged.get("targetPdbId")
    )
    target_chain = str(merged.get("targetChain") or merged.get("target_chain") or "A")[:1] or "A"
    target_range = str(merged.get("targetRange") or merged.get("target_range") or "1-150")
    hotspots = merged.get("hotspots") or []
    binder_length_range = (
        merged.get("binder_length_range")
        or merged.get("binderLengthRange")
        or [60, 150]
    )
    if not isinstance(binder_length_range, list) or len(binder_length_range) != 2:
        binder_length_range = [60, 150]
    num_designs = int(
        merged.get("num_designs") or merged.get("numDesigns") or 1
    )
    contigs = merged.get("contigs")
    inference_steps = int(
        merged.get("inference_steps") or merged.get("inferenceSteps") or 50
    )
    noise_scale = float(
        merged.get("noise_scale") or merged.get("noiseScale") or 1.0
    )

    events: list[dict] = []
    completed_seeds = 0
    total_outputs = 0
    try:
        for seed in seeds:
            seed_int = int(seed)
            result = _predict_impl(
                target_pdb=target_pdb,
                target_pdb_id=target_pdb_id,
                target_chain=target_chain,
                target_range=target_range,
                hotspots=hotspots,
                binder_length_range=list(binder_length_range),
                num_designs=num_designs,
                contigs=contigs,
                inference_steps=inference_steps,
                noise_scale=noise_scale,
                seed=seed_int,
            )

            if len(result["designs"]) != 1:
                raise RuntimeError(
                    f"RFdiffusion seed {seed_int} produced {len(result['designs'])} designs; expected 1"
                )
            for d in result["designs"]:
                idx = d["design_index"]
                artifact_key = _upload_structure(merged, seed_int, d["pdb_bytes"])
                event = {
                    "type": "seed",
                    "seed": seed_int,
                    "designId": f"{job_id}-s{seed_int}-d{idx}",
                    "artifactKey": artifact_key,
                    "structureKey": artifact_key,
                    "metrics": _numeric_metrics(d.get("metrics") or {}),
                }
                events.append(event)
                _emit_event(event)
                total_outputs += 1
            completed_seeds += 1

    except subprocess.CalledProcessError as exc:
        # RFdiffusion's CLI exits non-zero on contig parse errors and OOMs.
        # OOM (CUDA OOM) is retryable on a larger GPU; contig errors are not.
        msg = str(exc)
        retryable = "out of memory" in msg.lower() or "cuda" in msg.lower()
        event = {
            "type": "error",
            "code": "RFDIFF_SUBPROCESS_FAILED",
            "message": f"rfdiffusion failed: {msg}",
            "retryable": retryable,
        }
        events.append(event)
        _emit_event(event)
        return {"events": events}
    except Exception as exc:
        event = {
            "type": "error",
            "code": "RFDIFF_UNEXPECTED",
            "message": f"{type(exc).__name__}: {exc}",
            "retryable": False,
        }
        events.append(event)
        _emit_event(event)
        return {"events": events}

    summary = {
        "tool": "rfdiffusion",
        "seeds_completed": completed_seeds,
        "designs_emitted": total_outputs,
        "composes": ["proteinmpnn"],
    }
    done = {"type": "done", "summary": summary}
    events.append(done)
    _emit_event(done)
    return {"events": events, "summary": summary}


# ---------------------------------------------------------------------------
# Local entrypoint (manual smoke — do NOT auto-run, burns credits)
# ---------------------------------------------------------------------------

@app.local_entrypoint()
def main() -> None:
    """Tiny ubiquitin smoke: 1 seed, 1 design, no hotspots, 25 steps."""
    print("[local] Submitting RFdiffusion smoke (1UBQ, 1 design, 25 steps)...")
    result = predict.remote(
        target_pdb_id="1UBQ",
        target_chain="A",
        target_range="1-76",
        hotspots=None,
        binder_length_range=[60, 80],
        num_designs=1,
        inference_steps=25,
        noise_scale=1.0,
        seed=42,
    )
    print(f"[local] seed={result['seed']} outputs={result['num_outputs']} "
          f"contigs={result['contigs']} ckpt={result['ckpt']}")
    for d in result["designs"]:
        print(f"  design_index={d['design_index']} pdb={d['pdb_name']} "
              f"size={len(d['pdb_bytes'])}B metrics={json.dumps(d['metrics'])}")
    if not result["designs"]:
        raise SystemExit("FAIL: no designs returned")
    head = result["designs"][0]["pdb_bytes"][:160].decode("utf-8", errors="replace")
    print(f"[local] first PDB head: {head[:160].splitlines()[0] if head else ''}")
    print("[local] OK")


if __name__ == "__main__":
    # Allow `python modal_app.py` to print resolved config without invoking
    # Modal. Useful for adapter unit tests that just need to inspect the app
    # object / constants. Real execution path is `modal run`.
    print(json.dumps({
        "app": "papercrane-rfdiffusion",
        "gpu": GPU,
        "timeout_min": TIMEOUT_MIN,
        "rfdiffusion_sha": RFDIFFUSION_SHA,
        "weights_volume": WEIGHTS_VOLUME_NAME,
        "weights_files": list(WEIGHTS_FILES),
    }, indent=2))
