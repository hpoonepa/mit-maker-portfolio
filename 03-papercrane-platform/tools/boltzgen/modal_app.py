"""BoltzGen Modal app — ported from biomodals/modal_boltzgen.py for papercrane.

Source-of-truth: /Users/harsha/Desktop/claudeprojects/biomodals/modal_boltzgen.py
BoltzGen upstream: https://github.com/HannesStark/boltzgen

Image build: debian_slim + git clone @ 247b9bbd8b68a60aba854c2968d6a0cddd21ad6d,
then `pip install -e .` and `boltzgen download all` so weights are baked in.
Models are pre-downloaded at build time on an A100 GPU (`_download_boltzgen_models()`).

Functions:
  * design(yaml_str, yaml_name, additional_files, ...) -> list[(path, bytes)]
      Legacy local-CLI entrypoint, used by `main()` smoke test.
  * papercrane_dispatch(job_id, seeds, params, prev_output) -> dict
      Worker-facing NDJSON entrypoint for apps/worker. Emits one
      `{type:'seed',...}` JSON line per seed to stdout (plus `done` / `error`
      events). Per-seed exceptions are caught and reported via `error` events;
      the loop continues to the next seed.

Run smoke test:  modal run tools/boltzgen/modal_app.py
"""

import os
import json
from pathlib import Path

from modal import App, Image, Volume

# BoltzGen is an all-atom diffusion model; the larger 40 GB VRAM headroom on
# A100 is necessary for medium/large complexes. Manifest matches: A100-40GB.
GPU = os.environ.get("GPU", "A100-40GB")
TIMEOUT = int(os.environ.get("TIMEOUT", 120))

BOLTZGEN_COMMIT = "247b9bbd8b68a60aba854c2968d6a0cddd21ad6d"  # Dec 18 2025

CACHE_VOLUME_NAME = "papercrane-boltzgen-cache"
CACHE_VOLUME = Volume.from_name(CACHE_VOLUME_NAME, create_if_missing=True)
CACHE_DIR = f"/{CACHE_VOLUME_NAME}"


def _download_boltzgen_models():
    """Download all boltzgen models during image build to avoid runtime timeouts."""
    import subprocess

    print("Downloading boltzgen models...")
    subprocess.run(["boltzgen", "download", "all"], check=True)
    print("Model download complete")


image = (
    Image.debian_slim(python_version="3.11")
    .apt_install("git", "wget", "build-essential")
    .pip_install(
        "torch==2.5.1",
        extra_index_url="https://download.pytorch.org/whl/cu124",
    )
    .run_commands(
        "git clone https://github.com/HannesStark/boltzgen /root/boltzgen",
        # pytorch-lightning>=2.6 silently upgrades torch to a CUDA-13 build that
        # then fails nvrtc on Modal GPUs. Pin lightning + reinstall torch 2.5.1
        # after boltzgen install to keep the cu124 toolchain coherent.
        f"cd /root/boltzgen && git checkout {BOLTZGEN_COMMIT} && pip install -e . "
        f"&& pip install --force-reinstall --no-deps torch==2.5.1 "
        f"--extra-index-url https://download.pytorch.org/whl/cu124 "
        f"&& pip install pytorch-lightning==2.4.0",
        gpu="a10g",
    )
    .run_function(_download_boltzgen_models, gpu="A100-40GB")
)

app = App("boltzgen", image=image)


# ------------------------- Helpers ------------------------- #


def _classify_error(exc: BaseException) -> str:
    """Map an exception to an error `code` for NDJSON `error` events."""
    msg = str(exc).lower()
    if "cuda out of memory" in msg or "cuda oom" in msg or "out of memory" in msg:
        return "OOM"
    if isinstance(exc, TimeoutError) or "timeout" in msg or "timed out" in msg:
        return "TIMEOUT"
    if isinstance(exc, ValueError):
        return "INVALID_INPUT"
    if isinstance(exc, (ConnectionError, OSError)):
        return "INFRA_ERROR"
    return "RUNTIME_ERROR"


def _emit_event(event: dict) -> None:
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
    return {
        k: v
        for k, v in metrics.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }


def _upload_structure(merged: dict, seed: int, content: bytes) -> str | None:
    internal = merged.get("_papercrane")
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict):
        return None
    import urllib.request

    content_type = str(record.get("contentType") or "chemical/x-cif")
    request = urllib.request.Request(
        str(record["url"]), data=content, method="PUT", headers={"Content-Type": content_type}
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.status < 200 or response.status >= 300:
                raise OSError(f"artifact upload failed with status {response.status}")
    except Exception as exc:
        status = getattr(exc, "code", None)
        detail = f" (HTTP {status})" if status else ""
        raise OSError(f"artifact upload for seed {seed} failed{detail}") from exc
    return str(record["key"])


def _build_yaml_from_params(params: dict, seed: int) -> tuple[str, dict]:
    """Build a BoltzGen YAML spec + additional_files map from a params dict.

    Recognized fields (all optional unless noted):
      target_sequence   str  — protein target sequence (chain A). Mutually
                                exclusive with target_pdb_bytes.
      target_pdb        str  — name of target structure file inside
                                additional_files (e.g. "target.cif").
      target_pdb_bytes  bytes/base64 — raw bytes of target structure file.
      target_chain      str  — chain id to extract from target_pdb (default A).
      binder_length     int|str — binder length spec. Int -> "L..L"; str passed
                                through (e.g. "80..140").
      binder_chain      str  — id to assign to the designed binder (default C).
      ligand_sdf        str  — name of SDF file inside additional_files.
      ligand_sdf_bytes  bytes — raw bytes of an SDF ligand file.
      motif_pdb         str  — name of a motif scaffold file inside
                                additional_files.

    Returns (yaml_text, additional_files).
    """
    additional_files: dict = {}

    binder_chain = str(params.get("binder_chain", params.get("binderChain", "C")))[:1] or "C"
    target_chain = str(params.get("target_chain", params.get("targetChain", "A")))[:1] or "A"
    binder_length = params.get("binder_length", params.get("binderLength", "80..140"))
    if isinstance(binder_length, int):
        binder_length = f"{binder_length}..{binder_length}"
    elif isinstance(binder_length, (list, tuple)) and len(binder_length) == 2:
        lo, hi = binder_length
        binder_length = f"{int(lo)}..{int(hi)}"

    lines: list[str] = ["entities:"]

    # 1) Designed binder entity. If `target_sequence` is given we treat the
    #    target as a literal sequence entity; otherwise we expect a structure
    #    file (PDB/CIF) and only the binder gets a length-only sequence.
    lines += [
        "  - protein:",
        f"      id: {binder_chain}",
        f"      sequence: {binder_length}",
    ]

    # 2) Target — either a literal sequence or a structure file.
    target_sequence = params.get("target_sequence") or params.get("targetSequence") or params.get("targetSeq")
    target_pdb = params.get("target_pdb") or params.get("targetPdb")
    target_pdb_bytes = params.get("target_pdb_bytes")
    internal = params.get("_papercrane") if isinstance(params.get("_papercrane"), dict) else {}
    target_url = internal.get("targetStructureUrl")
    if target_url and not target_pdb_bytes:
        import urllib.request
        try:
            target_pdb_bytes = urllib.request.urlopen(str(target_url), timeout=30).read()
        except Exception as exc:
            status = getattr(exc, "code", None)
            detail = f" (HTTP {status})" if status else ""
            raise OSError(f"saved target fetch failed{detail}") from exc
        target_pdb = target_pdb or "target.pdb"

    # The public DesignRequest contract accepts a four-character RCSB id in
    # `targetPdb`. Resolve that id inside Modal so ordinary CLI/UI submissions
    # do not need to pre-stage a public structure in R2.
    if (
        isinstance(target_pdb, str)
        and len(target_pdb.strip()) == 4
        and target_pdb.strip().isalnum()
        and not target_pdb_bytes
    ):
        import urllib.request

        pdb_id = target_pdb.strip().upper()
        try:
            target_pdb_bytes = urllib.request.urlopen(
                f"https://files.rcsb.org/download/{pdb_id}.cif", timeout=30
            ).read()
        except Exception as exc:
            status = getattr(exc, "code", None)
            detail = f" (HTTP {status})" if status else ""
            raise OSError(f"RCSB target {pdb_id} fetch failed{detail}") from exc
        target_pdb = f"{pdb_id}.cif"

    if target_sequence:
        lines += [
            "  - protein:",
            f"      id: {target_chain}",
            f"      sequence: {target_sequence}",
        ]
    elif target_pdb or target_pdb_bytes:
        # If raw bytes given, stage as target.cif (or target.pdb).
        if target_pdb_bytes and not target_pdb:
            target_pdb = "target.cif"
        if target_pdb_bytes:
            additional_files[target_pdb] = _coerce_bytes(target_pdb_bytes)
        lines += [
            "  - file:",
            f"      path: {target_pdb}",
            "      include:",
            "        - chain:",
            f"            id: {target_chain}",
        ]
    else:
        raise ValueError(
            "params must include either `target_sequence` or `target_pdb`/`target_pdb_bytes`"
        )

    # 3) Optional ligand (SDF). BoltzGen supports ligand-aware design.
    ligand_sdf = params.get("ligand_sdf")
    ligand_sdf_bytes = params.get("ligand_sdf_bytes")
    if ligand_sdf_bytes and not ligand_sdf:
        ligand_sdf = "ligand.sdf"
    if ligand_sdf_bytes:
        additional_files[ligand_sdf] = _coerce_bytes(ligand_sdf_bytes)
    if ligand_sdf:
        lines += [
            "  - ligand:",
            f"      path: {ligand_sdf}",
        ]

    # 4) Optional motif scaffold.
    motif_pdb = params.get("motif_pdb")
    motif_pdb_bytes = params.get("motif_pdb_bytes")
    if motif_pdb_bytes and not motif_pdb:
        motif_pdb = "motif.pdb"
    if motif_pdb_bytes:
        additional_files[motif_pdb] = _coerce_bytes(motif_pdb_bytes)
    if motif_pdb:
        lines += [
            "  - file:",
            f"      path: {motif_pdb}",
        ]

    return "\n".join(lines) + "\n", additional_files


def _coerce_bytes(value) -> bytes:
    """Accept bytes, bytearray, str (utf-8), or base64-encoded str."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        # Try base64 first (no exception => safe fallback to utf-8 bytes).
        try:
            import base64
            return base64.b64decode(value, validate=True)
        except Exception:
            return value.encode("utf-8")
    raise TypeError(f"cannot coerce {type(value).__name__} to bytes")


def _run_boltzgen_subprocess(
    yaml_str: str,
    yaml_name: str,
    additional_files: dict,
    protocol: str,
    num_designs: int,
    seed: int | None = None,
    steps: str | None = None,
    cache: str | None = None,
    devices: int | None = None,
    extra_args: str | None = None,
) -> list[tuple[str, bytes]]:
    """Shared subprocess invocation for both `design()` and dispatch loop.

    Returns list of (relative_path, content_bytes) for every output file.
    Raises RuntimeError on non-zero exit code.
    """
    import subprocess
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as in_dir, TemporaryDirectory() as out_dir:
        yaml_path = Path(in_dir) / yaml_name
        yaml_path.write_text(yaml_str)

        for rel_path, content in additional_files.items():
            file_path = Path(in_dir) / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(content)

        cmd = [
            "boltzgen", "run", str(yaml_path),
            "--output", out_dir,
            "--protocol", protocol,
            "--num_designs", str(num_designs),
        ]
        # BoltzGen's `run` CLI does not expose a --seed option. `seed` remains
        # the platform's stable design identifier, while BoltzGen owns its
        # internal sampling RNG for this invocation.
        if steps:
            cmd.extend(["--steps"] + steps.split())
        if cache:
            cmd.extend(["--cache", cache])
        if devices:
            cmd.extend(["--devices", str(devices)])
        if extra_args:
            cmd.extend(extra_args.split())

        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stdout:
            print("--- boltzgen stdout ---")
            print(result.stdout)
        if result.stderr:
            print("--- boltzgen stderr ---")
            print(result.stderr)
        if result.returncode != 0:
            stderr_tail = (result.stderr or "").strip()[-2000:]
            raise RuntimeError(
                f"boltzgen exited {result.returncode}: {stderr_tail or 'no stderr'}"
            )

        return [
            (str(out_file.relative_to(out_dir)), out_file.read_bytes())
            for out_file in Path(out_dir).rglob("*")
            if out_file.is_file()
        ]


def _extract_metrics_from_outputs(outputs: list[tuple[str, bytes]]) -> list[dict]:
    """Select ranked complexes and attach BoltzGen CSV/JSON metrics.

    Returns list of {design_id, structure_path, metrics, all_files: [paths]}
    sorted by rank. Input-spec visualizations are deliberately excluded when
    a refolded ranked structure exists.
    """
    import csv
    import io
    import re

    structures: list[str] = []
    json_metrics: dict[str, dict] = {}
    csv_rows: list[dict] = []

    for rel_path, content in outputs:
        p = Path(rel_path)
        if p.suffix.lower() in (".pdb", ".cif"):
            structures.append(rel_path)
        elif p.suffix.lower() == ".json":
            try:
                meta = json.loads(content.decode("utf-8"))
                if isinstance(meta, dict):
                    json_metrics[p.stem] = meta
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
        elif p.name == "all_designs_metrics.csv":
            try:
                csv_rows = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))
            except (UnicodeDecodeError, csv.Error):
                pass

    def structure_priority(path: str) -> int:
        parts = Path(path).parts
        if "before_refolding" in parts:
            return 8
        if "final_ranked_designs" in parts and any(
            part != "final_ranked_designs"
            and part.startswith("final_")
            and part.endswith("_designs")
            for part in parts
        ):
            return 0
        if "intermediate_ranked_10_designs" in parts:
            return 1
        if "refold_cif" in parts:
            return 2
        if "intermediate_designs_inverse_folded" in parts:
            return 4
        if len(parts) == 1:
            return 9
        return 6

    if not structures:
        return []
    best_priority = min(structure_priority(path) for path in structures)
    selected = sorted(path for path in structures if structure_priority(path) == best_priority)

    def normalized_stem(path: str) -> str:
        return re.sub(r"^rank\d+_", "", Path(path).stem)

    def matching_row(path: str, index: int) -> dict:
        stem = normalized_stem(path)
        for row in csv_rows:
            row_id = str(row.get("id") or "")
            file_stem = Path(str(row.get("file_name") or "")).stem
            if stem in (row_id, file_stem):
                return row
        return csv_rows[min(index, len(csv_rows) - 1)] if csv_rows else {}

    metric_columns = {
        "iptm": (
            "design_to_target_iptm",
            "designfolding-design_to_target_iptm",
            "iptm",
        ),
        "ptm": ("design_ptm", "designfolding-design_ptm", "ptm"),
        "pae_mean": (
            "min_design_to_target_pae",
            "designfolding-min_design_to_target_pae",
        ),
        "filter_rmsd": ("filter_rmsd",),
        "designfolding_rmsd": ("designfolding-filter_rmsd",),
        "plip_hbonds_refolded": ("plip_hbonds_refolded",),
        "delta_sasa_refolded": ("delta_sasa_refolded",),
        "quality_score": ("quality_score",),
    }

    summaries: list[dict] = []
    for index, structure_path in enumerate(selected):
        stem = normalized_stem(structure_path)
        row = matching_row(structure_path, index)
        metrics: dict = {}
        meta = json_metrics.get(stem) or {}
        for key, value in meta.items():
            if isinstance(value, (int, float)):
                metrics[key] = value
        for metric, columns in metric_columns.items():
            for column in columns:
                value = row.get(column)
                if value not in (None, ""):
                    try:
                        metrics[metric] = float(value)
                        break
                    except (TypeError, ValueError):
                        pass
        sequence = row.get("designed_sequence") or row.get("designed_chain_sequence")
        if isinstance(sequence, str) and sequence:
            metrics["sequence"] = sequence
            metrics["length"] = len(sequence)
        pass_filters = str(row.get("pass_filters") or "").lower()
        if pass_filters in ("true", "false"):
            metrics["pass_filters"] = pass_filters == "true"
        summaries.append({
            "design_id": str(row.get("id") or stem),
            "structure_path": structure_path,
            "metrics": metrics,
            "files": [
                rel_path
                for rel_path, _content in outputs
                if normalized_stem(rel_path) == stem
            ],
        })
    return summaries


# ------------------------- Legacy design() entrypoint ------------------------- #


@app.function(timeout=TIMEOUT * 60, gpu=GPU, volumes={CACHE_DIR: CACHE_VOLUME})
def design(
    yaml_str: str,
    yaml_name: str,
    additional_files: dict,
    protocol: str = "protein-anything",
    num_designs: int = 1,
    steps: str | None = None,
    cache: str | None = None,
    devices: int | None = None,
    extra_args: str | None = None,
) -> list:
    """Run BoltzGen on a yaml specification. (Legacy local-CLI entrypoint.)

    Args:
        yaml_str: YAML design specification as string
        yaml_name: Name of the yaml file
        additional_files: Dict of relative_path -> file_content for files referenced in yaml
        protocol: protein-anything | peptide-anything | protein-small_molecule | nanobody-anything
        num_designs: Number of designs to generate (default 1 for tests)
        steps: Specific pipeline steps to run (e.g. "design inverse_folding folding")
        cache: Custom cache directory
        devices: Number of GPUs
        extra_args: Additional CLI args as a single string

    Returns:
        List of (relative_path, content_bytes) tuples for every output file.
    """
    return _run_boltzgen_subprocess(
        yaml_str=yaml_str,
        yaml_name=yaml_name,
        additional_files=additional_files,
        protocol=protocol,
        num_designs=num_designs,
        steps=steps,
        cache=cache,
        devices=devices,
        extra_args=extra_args,
    )


# ------------------------- Worker-facing dispatch ------------------------- #


@app.function(timeout=TIMEOUT * 60, gpu=GPU, volumes={CACHE_DIR: CACHE_VOLUME})
def papercrane_dispatch(
    job_id: str,
    seeds,
    params=None,
    prev_output=None,
) -> dict:
    """Worker-facing NDJSON entrypoint used by apps/worker.

    For each seed:
      1. Builds a BoltzGen YAML from `params` (supports literal target sequence,
         staged target PDB/CIF, optional ligand SDF, optional motif PDB).
      2. Invokes the `boltzgen run` subprocess for the platform seed.
      3. Parses any per-design metric JSON sidecars from the output dir.
      4. Emits one NDJSON `seed` event per produced design (artifactKey points
         at where the worker will persist the file in R2/S3).
      5. On per-seed exceptions: emits an `error` event (classified) and
         continues to the next seed.

    Returns a summary dict (also echoed via a `done` event).
    The full output bytes are still returned as `artifacts` for the caller to
    persist (matches chai1/boltz2 pattern).
    """
    seeds = _json_arg(seeds, []) or []
    params = _json_arg(params, {}) or {}
    prev_output = _json_arg(prev_output, None)

    tool_params = (
        params.get("toolParams") if isinstance(params.get("toolParams"), dict) else {}
    ) or {}
    merged = {**params, **tool_params}

    protocol = str(merged.get("protocol", "protein-anything"))
    # The platform's `numDesigns` already expands to one seed per design. Do
    # not multiply that count again inside each seed.
    num_designs = int(merged.get("designs_per_seed", merged.get("designsPerSeed", 1)))
    steps = merged.get("steps")
    devices = merged.get("devices")
    extra_args = merged.get("extra_args") or merged.get("extraArgs") or "--use_kernels false"

    completed = 0
    failed_seeds = 0
    all_artifacts: list[tuple[str, bytes]] = []
    seed_summaries: list[dict] = []

    for raw_seed in seeds:
        try:
            seed_int = int(raw_seed)
        except (TypeError, ValueError):
            _emit_event({
                "type": "error",
                "seed": raw_seed,
                "code": "INVALID_INPUT",
                "message": f"seed must be int-coercible, got {type(raw_seed).__name__}",
                "retryable": False,
            })
            failed_seeds += 1
            continue

        try:
            yaml_str, additional_files = _build_yaml_from_params(merged, seed_int)
            outputs = _run_boltzgen_subprocess(
                yaml_str=yaml_str,
                yaml_name=f"design_seed{seed_int}.yaml",
                additional_files=additional_files,
                protocol=protocol,
                num_designs=num_designs,
                seed=seed_int,
                steps=steps,
                # Models are downloaded into the image during build. A named
                # volume is workspace-local, so BYOC workspaces start with an
                # empty cache and BoltzGen tries to fetch weights again.
                cache=None,
                devices=int(devices) if devices else None,
                extra_args=extra_args,
            )

            design_summaries = _extract_metrics_from_outputs(outputs)
            if not design_summaries:
                # No structure files at all — treat as runtime error.
                raise RuntimeError(
                    f"boltzgen produced no structure files for seed {seed_int}"
                )

            # Stash the seed-scoped artifacts (rel_path is rewritten so the
            # caller can flatten everything under `modal/<job_id>/boltzgen/<seed>/`).
            for rel_path, content in outputs:
                all_artifacts.append(
                    (f"modal/{job_id}/boltzgen/{seed_int}/{rel_path}", content)
                )

            # The DB contract is unique(job_id, seed), so the canonical first
            # structure is the platform artifact for this seed.
            ds = design_summaries[0]
            structure_bytes = next(
                (
                    content
                    for rel_path, content in outputs
                    if rel_path == ds["structure_path"]
                    or Path(rel_path).name == Path(ds["structure_path"]).name
                ),
                None,
            )
            if not structure_bytes:
                raise RuntimeError("boltzgen structure bytes were not found in outputs")
            artifact_key = _upload_structure(merged, seed_int, structure_bytes)
            _emit_event({
                "type": "seed",
                "seed": seed_int,
                "designId": f"{job_id}-s{seed_int}-{ds['design_id']}",
                "sequence": (ds.get("metrics") or {}).get("sequence"),
                "metrics": _numeric_metrics(ds.get("metrics") or {}),
                "artifactKey": artifact_key or f"modal/{job_id}/boltzgen/{seed_int}/{ds['structure_path']}",
            })
            completed += 1

            seed_summaries.append({
                "seed": seed_int,
                "designs": [ds["design_id"] for ds in design_summaries],
            })

        except Exception as exc:
            code = _classify_error(exc)
            _emit_event({
                "type": "error",
                "seed": seed_int,
                "code": code,
                "message": str(exc)[:500],
                "retryable": code in ("OOM", "TIMEOUT", "INFRA_ERROR"),
            })
            failed_seeds += 1
            # Continue — other seeds may succeed.

    summary = {
        "tool": "boltzgen",
        "completed": completed,
        "failed_seeds": failed_seeds,
        "seeds": seed_summaries,
    }
    _emit_event({"type": "done", "summary": summary})
    return {
        "summary": summary,
        "artifacts": all_artifacts,
    }


# ------------------------- Local entrypoint (smoke test) ------------------------- #

# Minimal yaml fixture lifted from biomodals/tests/test_quick_runs.py::test_boltzgen.
# Designs a binder (length 80..140) for chain A of 1g13. The .cif is fetched live
# from the BoltzGen example repo so this entrypoint is self-contained.
_TEST_YAML = """entities:
  - protein:
      id: C
      sequence: 80..140
  - file:
      path: 1g13.cif
      include:
        - chain:
            id: A
"""

_TEST_CIF_URL = (
    "https://raw.githubusercontent.com/HannesStark/boltzgen/refs/heads/main/"
    "example/vanilla_protein/1g13.cif"
)


@app.local_entrypoint()
def main(num_designs: int = 1, out_dir: str = "./out/boltzgen"):
    """Smoke test: design a single binder against 1g13 chain A."""
    import urllib.request
    from datetime import datetime

    print(f"Fetching test target: {_TEST_CIF_URL}")
    with urllib.request.urlopen(_TEST_CIF_URL) as r:
        cif_bytes = r.read()
    print(f"  got {len(cif_bytes)} bytes")

    outputs = design.remote(
        yaml_str=_TEST_YAML,
        yaml_name="1g13prot.yaml",
        additional_files={"1g13.cif": cif_bytes},
        protocol="protein-anything",
        num_designs=num_designs,
        extra_args="--use_kernels false",
    )

    today = datetime.now().strftime("%Y%m%d%H%M")[2:]
    out_root = Path(out_dir) / today

    pdb_count = 0
    sample = None
    for rel_path, content in outputs:
        target = out_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        if rel_path.endswith(".pdb") or rel_path.endswith(".cif"):
            pdb_count += 1
            if sample is None:
                sample = (rel_path, len(content))

    print(f"\nResults saved to: {out_root}")
    print(f"Total files: {len(outputs)}  |  Structure files (.pdb/.cif): {pdb_count}")
    if sample:
        print(f"Sample structure: {sample[0]}  ({sample[1]} bytes)")
