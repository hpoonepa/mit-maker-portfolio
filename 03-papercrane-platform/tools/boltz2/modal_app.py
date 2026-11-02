# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "modal>=1.0",
# ]
# ///
"""Paper Crane Boltz-2 Modal app.

Minimal port of biomodals/modal_boltz.py for the Paper Crane tool layer.
- Stock pip `boltz==2.2.1` (NOT the mosaic-internal jax variant).
- Reuses the `boltz-models` volume at /boltz-models so cached weights are
  shared with anything else that mounts it.

Single function: `predict(target_seq, binder_seq=None, ..., seed=42)`.
Returns {confidence: {plddt, ipTM, ptm, ipae_mean, plddt_binder, per_chain_ptm},
         cif_bytes: bytes, structure_path: str}.

Local entrypoint runs a tiny ubiquitin chain-A smoke test.
"""
import os
import json
from pathlib import Path

import modal

# L40S is sufficient for Boltz-2 inference; A100-80GB only needed for very large complexes (>2000 residues total).
GPU = os.environ.get("GPU", "L40S")
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", 60))

BOLTZ_VOLUME_NAME = "boltz-models"
BOLTZ_VOLUME = modal.Volume.from_name(BOLTZ_VOLUME_NAME, create_if_missing=True)
CACHE_DIR = f"/{BOLTZ_VOLUME_NAME}"


def _download_models():
    """Force-download Boltz-2 weights into the mounted volume (one-time)."""
    from boltz.main import download_boltz2

    if not Path(f"{CACHE_DIR}/boltz2_conf.ckpt").exists():
        print(f"Downloading Boltz-2 weights into {CACHE_DIR} ...")
        download_boltz2(Path(CACHE_DIR))
        print("Done.")
    else:
        print("Boltz-2 weights already cached.")


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("wget", "git", "build-essential")
    .pip_install(
        "boltz==2.2.1",
        "pyyaml",
        "numpy",
    )
    # Note: we run with `--no_kernels` so we don't need cuequivariance-torch /
    # cuequivariance-ops-torch-cu12. Skipping them avoids CUDA-12/13 nvrtc
    # mismatches with torch 2.11 inside the modal image.
    .run_function(
        _download_models,
        gpu="a10g",
        volumes={CACHE_DIR: BOLTZ_VOLUME},
    )
)

app = modal.App("boltz2", image=image)

SMOKE_SEQUENCE = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"


def _emit_yaml(target_seq: str, binder_seq: str | None) -> str:
    lines = [
        "version: 1",
        "sequences:",
        "  - protein:",
        "      id: A",
        f"      sequence: {target_seq}",
    ]
    if binder_seq:
        lines += [
            "  - protein:",
            "      id: B",
            f"      sequence: {binder_seq}",
        ]
    return "\n".join(lines) + "\n"


def _sequence_from_pdb(pdb_id: str | None, chain_id: str | None = None) -> str | None:
    if not pdb_id or len(str(pdb_id)) != 4:
        return None
    import urllib.request

    url = f"https://www.rcsb.org/fasta/entry/{str(pdb_id).upper()}/display"
    try:
        text = urllib.request.urlopen(url, timeout=20).read().decode("utf-8")
    except Exception as exc:
        print(f"Could not fetch FASTA for {pdb_id}: {exc}")
        return None

    records: list[tuple[str, str]] = []
    header: str | None = None
    seq: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header and seq:
                records.append((header, "".join(seq)))
            header = line[1:]
            seq = []
        else:
            seq.append(line)
    if header and seq:
        records.append((header, "".join(seq)))

    wanted = str(chain_id).upper() if chain_id else None
    if wanted:
        for rec_header, rec_seq in records:
            if f"|Chains {wanted}" in rec_header or f"|Chain {wanted}" in rec_header:
                return rec_seq
    return records[0][1] if records else None


def _sequence_from_structure_url(url: str | None, chain_id: str | None = None) -> str | None:
    """Download an org-scoped PDB upload and extract one protein chain."""
    if not url:
        return None
    import urllib.request

    text = urllib.request.urlopen(url, timeout=30).read().decode("utf-8", "replace")
    aa3 = {
        "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
        "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
        "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
        "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
        "MSE": "M",
    }
    wanted = str(chain_id).strip()[:1] if chain_id else None
    seen: set[tuple[str, str, str]] = set()
    sequence: list[str] = []
    selected_chain: str | None = wanted
    for line in text.splitlines():
        if not line.startswith("ATOM") or len(line) < 27:
            continue
        chain = line[21].strip() or "A"
        if selected_chain is None:
            selected_chain = chain
        if chain != selected_chain:
            continue
        key = (chain, line[22:26].strip(), line[26].strip())
        if key in seen:
            continue
        seen.add(key)
        residue = aa3.get(line[17:20].strip().upper())
        if residue:
            sequence.append(residue)
    if not sequence and "_atom_site." in text:
        import shlex

        lines = text.splitlines()
        index = 0
        while index < len(lines):
            if lines[index].strip() != "loop_":
                index += 1
                continue
            index += 1
            headers: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("_"):
                headers.append(lines[index].strip())
                index += 1
            if not headers or not all(h.startswith("_atom_site.") for h in headers):
                continue
            columns = {name.split(".", 1)[1]: pos for pos, name in enumerate(headers)}
            comp_col = columns.get("auth_comp_id", columns.get("label_comp_id"))
            chain_col = columns.get("auth_asym_id", columns.get("label_asym_id"))
            seq_col = columns.get("auth_seq_id", columns.get("label_seq_id"))
            group_col = columns.get("group_PDB")
            ins_col = columns.get("pdbx_PDB_ins_code")
            if comp_col is None or chain_col is None or seq_col is None:
                continue
            while index < len(lines):
                raw = lines[index].strip()
                if not raw or raw == "#" or raw == "loop_" or raw.startswith("_"):
                    break
                index += 1
                values = shlex.split(raw)
                if len(values) < len(headers):
                    continue
                if group_col is not None and values[group_col].upper() != "ATOM":
                    continue
                chain = values[chain_col]
                if selected_chain is None:
                    selected_chain = chain
                if chain != selected_chain:
                    continue
                insertion = values[ins_col] if ins_col is not None else ""
                key = (chain, values[seq_col], insertion)
                if key in seen:
                    continue
                seen.add(key)
                residue = aa3.get(values[comp_col].upper())
                if residue:
                    sequence.append(residue)
            if sequence:
                break
    if not sequence:
        raise ValueError("uploaded target contains no parseable PDB/mmCIF ATOM residues")
    return "".join(sequence)


def _upload_structure(merged: dict, seed: int, content: bytes) -> str | None:
    internal = merged.get("_papercrane")
    if not isinstance(internal, dict):
        return None
    uploads = internal.get("artifactUploads")
    record = uploads.get(str(seed)) if isinstance(uploads, dict) else None
    if not isinstance(record, dict):
        return None
    import urllib.request

    content_type = str(record.get("contentType") or "chemical/x-cif")
    request = urllib.request.Request(
        str(record["url"]), data=content, method="PUT", headers={"Content-Type": content_type}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"artifact upload failed with status {response.status}")
    return str(record["key"])


def _resolve_cofold(merged: dict, params: dict) -> tuple[str, str | None]:
    """Resolve (target_seq, binder_seq) for a co-fold from merged params.

    Target precedence: targetSeq/target_seq/sequence > sequences[0] >
    targetPdb (honoring targetChain) > SMOKE_SEQUENCE.
    Binder precedence: binderSeq/binder_seq > binders[0].sequence >
    sequences[1] > partnerPdb (a 2nd structure, honoring partnerChain) > None.
    Supporting the canonical ``sequences`` records is especially important for
    Boltz-1, whose dashboard input is sequence-based and reuses this resolver.
    """
    internal = merged.get("_papercrane") if isinstance(merged.get("_papercrane"), dict) else {}
    sequence_values = merged.get("sequences")
    canonical_sequences: list[str] = []
    if isinstance(sequence_values, list):
        for value in sequence_values:
            sequence = value.get("sequence") if isinstance(value, dict) else value
            if sequence:
                canonical_sequences.append(str(sequence))
    target_ref = merged.get("targetPdb") or params.get("targetPdb")
    target_seq = (
        merged.get("targetSeq")
        or merged.get("target_seq")
        or merged.get("sequence")
        or (canonical_sequences[0] if canonical_sequences else None)
        or _sequence_from_pdb(
            target_ref,
            merged.get("targetChain"),
        )
    )
    if not target_seq and internal.get("targetStructureUrl"):
        target_seq = _sequence_from_structure_url(
            internal.get("targetStructureUrl"), merged.get("targetChain")
        )
    if not target_seq and target_ref:
        raise ValueError(f"could not resolve target {target_ref!r}")
    target_seq = target_seq or SMOKE_SEQUENCE

    binder_seq = merged.get("binderSeq") or merged.get("binder_seq")
    if not binder_seq:
        binders = merged.get("binders")
        if isinstance(binders, list) and binders and isinstance(binders[0], dict):
            binder_seq = binders[0].get("sequence")
    if not binder_seq and len(canonical_sequences) > 1:
        binder_seq = canonical_sequences[1]
    partner_ref = merged.get("partnerPdb") or params.get("partnerPdb")
    if not binder_seq:
        binder_seq = _sequence_from_pdb(
            partner_ref,
            merged.get("partnerChain"),
        )
    if not binder_seq and internal.get("partnerStructureUrl"):
        binder_seq = _sequence_from_structure_url(
            internal.get("partnerStructureUrl"), merged.get("partnerChain")
        )
    if not binder_seq and partner_ref:
        raise ValueError(f"could not resolve partner {partner_ref!r}")

    return str(target_seq), (str(binder_seq) if binder_seq else None)


def _binder_sequence_from_prev(prev_output: object, seed: int) -> str | None:
    if not isinstance(prev_output, dict) or not isinstance(prev_output.get("designs"), list):
        return None
    designs = prev_output["designs"]
    for design in designs:
        if isinstance(design, dict) and int(design.get("seed", -1)) == seed and design.get("sequence"):
            return str(design["sequence"])
    for design in designs:
        if isinstance(design, dict) and design.get("sequence"):
            return str(design["sequence"])
    return None


@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    buffer_containers=1,
    scaledown_window=300,
    volumes={CACHE_DIR: BOLTZ_VOLUME},
)
def predict(
    target_seq: str,
    binder_seq: str | None = None,
    recycling_steps: int = 3,
    sampling_steps: int = 50,
    diffusion_samples: int = 1,
    seed: int = 42,
    use_msa_server: bool = True,
) -> dict:
    """Run Boltz-2 on a single (target [+ optional binder]) co-fold.

    Returns a dict with confidence metrics + CIF bytes for the top sample.
    """
    return _predict_impl(
        target_seq=target_seq,
        binder_seq=binder_seq,
        recycling_steps=recycling_steps,
        sampling_steps=sampling_steps,
        diffusion_samples=diffusion_samples,
        seed=seed,
        use_msa_server=use_msa_server,
    )


def _predict_impl(
    target_seq: str,
    binder_seq: str | None = None,
    recycling_steps: int = 3,
    sampling_steps: int = 50,
    diffusion_samples: int = 1,
    seed: int = 42,
    use_msa_server: bool = True,
) -> dict:
    import json as py_json
    from subprocess import run
    from tempfile import TemporaryDirectory

    yaml_text = _emit_yaml(target_seq, binder_seq)

    with TemporaryDirectory() as in_dir, TemporaryDirectory() as out_dir:
        cfg_path = Path(in_dir) / "in.yaml"
        cfg_path.write_text(yaml_text)

        cmd = [
            "boltz", "predict", str(cfg_path),
            "--out_dir", str(out_dir),
            "--cache", CACHE_DIR,
            "--recycling_steps", str(recycling_steps),
            "--sampling_steps", str(sampling_steps),
            "--diffusion_samples", str(diffusion_samples),
            "--seed", str(seed),
            "--no_kernels",
        ]
        if use_msa_server:
            cmd.append("--use_msa_server")

        print("Running:", " ".join(cmd))
        run(cmd, check=True)

        cifs = sorted(Path(out_dir).rglob("*.cif"))
        if not cifs:
            raise RuntimeError(f"Boltz produced no CIFs under {out_dir}")
        top_cif = cifs[0]
        cif_bytes = top_cif.read_bytes()

        confidence: dict = {}
        conf_files = sorted(Path(out_dir).rglob("confidence_*.json"))
        if conf_files:
            conf = py_json.loads(conf_files[0].read_text())
            # Keep upstream names and values: complex_pde is predicted
            # distance error, not interface PAE. Missing metrics stay absent.
            confidence = _numeric_metrics(conf)


        return {
            "structure_path": str(top_cif.relative_to(out_dir)),
            "cif_bytes": cif_bytes,
            "confidence": confidence,
        }


def _numeric_metrics(metrics: dict) -> dict:
    import math

    return {k: v for k, v in metrics.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}


def _emit_event(event: dict) -> None:
    print(json.dumps(event), flush=True)


def _classify_error(exc: BaseException) -> str:
    msg = str(exc).lower()
    if "cuda out of memory" in msg:
        return "OOM"
    if isinstance(exc, TimeoutError) or "timeout" in msg or "timed out" in msg:
        return "TIMEOUT"
    if isinstance(exc, ValueError):
        return "INVALID_INPUT"
    if isinstance(exc, (ConnectionError, OSError)):
        return "INFRA_ERROR"
    return "RUNTIME_ERROR"


def _json_arg(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    volumes={CACHE_DIR: BOLTZ_VOLUME},
)
def papercrane_dispatch(
    job_id: str,
    seeds,
    params=None,
    prev_output=None,
) -> dict:
    """Worker-facing NDJSON entrypoint used by apps/worker."""
    seeds = _json_arg(seeds, [])
    params = _json_arg(params, {}) or {}
    prev_output = _json_arg(prev_output, None)
    tool_params = params.get("toolParams") if isinstance(params.get("toolParams"), dict) else {}
    merged = {**params, **tool_params}
    target_seq, explicit_binder_seq = _resolve_cofold(merged, params)

    recycling_steps = int(merged.get("recycling_steps", merged.get("recyclingSteps", 3)))
    sampling_steps = int(merged.get("sampling_steps", merged.get("samplingSteps", 50)))
    diffusion_samples = int(merged.get("diffusion_samples", merged.get("diffusionSamples", 1)))
    use_msa_server = bool(merged.get("use_msa_server", merged.get("useMsa", True)))

    events: list[dict] = []
    completed = 0
    failed_seeds = 0
    for seed in seeds:
        binder_seq = explicit_binder_seq or _binder_sequence_from_prev(
            prev_output, int(seed)
        )
        try:
            result = _predict_impl(
                target_seq=str(target_seq),
                binder_seq=str(binder_seq) if binder_seq else None,
                recycling_steps=recycling_steps,
                sampling_steps=sampling_steps,
                diffusion_samples=diffusion_samples,
                seed=int(seed),
                use_msa_server=use_msa_server,
            )
        except Exception as exc:
            code = _classify_error(exc)
            event = {
                "type": "error",
                "seed": int(seed),
                "code": code,
                "message": str(exc)[:500],
                "retryable": code in ("OOM", "TIMEOUT", "INFRA_ERROR"),
            }
            events.append(event)
            _emit_event(event)
            failed_seeds += 1
            continue

        artifact_key = _upload_structure(merged, int(seed), result["cif_bytes"])
        event = {
            "type": "seed",
            "seed": int(seed),
            "artifactKey": artifact_key or f"modal/{job_id}/boltz2/{seed}/{result['structure_path']}",
            "metrics": {
                **_numeric_metrics(result.get("confidence") or {}),
                # _emit_yaml always writes target chain A and only writes B
                # when a binder sequence was supplied for this prediction.
                "chain_count": 2 if binder_seq else 1,
            },
        }
        events.append(event)
        _emit_event(event)
        completed += 1

    summary = {"tool": "boltz2", "completed": completed, "failed_seeds": failed_seeds}
    done = {"type": "done", "summary": summary, "failed_seeds": failed_seeds}
    events.append(done)
    _emit_event(done)
    return {"events": events, "summary": summary}


@app.local_entrypoint()
def main():
    """Smoke test: fold human ubiquitin (UBC chain A, 76 aa) on Modal."""
    ubiquitin = (
        "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"
    )
    print(f"Submitting Boltz-2 predict for ubiquitin ({len(ubiquitin)} aa)...")
    result = predict.remote(
        target_seq=ubiquitin,
        binder_seq=None,
        recycling_steps=1,
        sampling_steps=50,
        diffusion_samples=1,
        seed=42,
        use_msa_server=True,
    )
    conf = result.get("confidence") or {}
    print("=== Boltz-2 result ===")
    print(f"  structure_path: {result.get('structure_path')}")
    print(f"  cif size:       {len(result.get('cif_bytes', b''))} bytes")
    print(f"  plddt_mean:     {conf.get('plddt_mean')}")
    print(f"  ptm:            {conf.get('ptm')}")
    print(f"  iptm:           {conf.get('iptm')}")
    print(f"  ipae_mean:      {conf.get('ipae_mean')}")
    if not result.get("cif_bytes"):
        raise SystemExit("FAIL: no CIF bytes returned")
    print("OK: structure was returned.")
