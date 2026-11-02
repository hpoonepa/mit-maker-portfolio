"""Paper Crane: AlphaFold 3-compatible inference via Protenix on Modal.

This is the production backend for the `alphafold3` tool slot. It runs
Protenix (https://github.com/bytedance/Protenix), an open-source PyTorch
reimplementation of AlphaFold 3. The legacy HTTPS adapter is retained only
for deployments that provide their own remote service.

App name: "alphafold3" (Modal app namespace; the tool id and the app share a name
so log searches on either term land in the same place).

Quick test:
    modal run tools/alphafold3/modal_app.py

The default `local_entrypoint` runs the cheap `protenix_mini_default_v0.5.0`
variant on ubiquitin (chain A) with a single seed and no MSA, which is the
fastest end-to-end smoke test.

Source-of-truth (read-only, do not edit): biomodals/modal_protenix.py
"""

import os
import json
from pathlib import Path

from modal import App, Image

GPU = os.environ.get("GPU", "L40S")
TIMEOUT = int(os.environ.get("TIMEOUT", 60))

ENTITY_TYPES = {"protein", "dna", "rna", "ligand", "ion"}
ENTITY_TYPE_MAP = {
    "protein": "proteinChain",
    "dna": "dnaSequence",
    "rna": "rnaSequence",
    "ligand": "ligand",
    "ion": "ion",
}

# Cheap mini variant; the full base model is "protenix_base_20250630_v1.0.0".
DEFAULT_MODEL = "protenix_mini_default_v0.5.0"
DEFAULT_SEEDS = "42"
SMOKE_FASTA = (
    ">protein|A\n"
    "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG\n"
)


def download_models():
    """Force download/initialization of Protenix mini model by running once.

    Mirrors biomodals/modal_protenix.py::download_models but pulls the mini
    variant so the image size and per-call inference cost stay low.
    """
    from subprocess import run
    from tempfile import TemporaryDirectory

    Path(out_dir := "/tmp/out_dm").mkdir(parents=True, exist_ok=True)

    test_json = """[
    {
        "name": "test",
        "sequences": [
            {
                "proteinChain": {
                    "sequence": "MAWTPLLLLLLSHCTGSLSQPVLTQPTSL",
                    "count": 1
                }
            }
        ]
    }
]"""

    with TemporaryDirectory() as td:
        json_path = Path(td) / "test.json"
        json_path.write_text(test_json)

        print(f"Downloading Protenix model: {DEFAULT_MODEL} ...")
        run(
            f'protenix pred --input "{json_path}" --out_dir "{out_dir}" '
            f"--seeds 42 --use_msa false --model_name {DEFAULT_MODEL}",
            shell=True,
            check=True,
        )

    print("Model download complete")


image = (
    Image.from_registry("nvidia/cuda:12.6.3-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .apt_install("git", "wget", "g++", "gcc", "make", "clang")
    .pip_install("protenix==1.0.4")
    .env({"CUDA_HOME": "/usr/local/cuda"})
    .run_function(download_models, gpu="A10G")
)

# We name the Modal app "alphafold3" so it lines up with the tool id in
# manifest.json. Logs and dashboards key on this; do not rename without
# updating the adapter that may eventually dispatch to this app.
app = App("alphafold3", image=image)


def _fasta_to_json(input_faa: str, name: str = "input") -> str:
    """Convert FASTA to Protenix JSON format. Vendored from modal_protenix.py."""
    import json
    import re

    rx = re.compile(r"^([^|]+)\|([^|]*)\|?(.*)$")
    sequences = []

    current_id = None
    current_seq: list[str] = []
    for line in input_faa.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if current_id is not None:
                sequences.append((current_id, "".join(current_seq)))
            current_id = line[1:].strip()
            current_seq = []
        else:
            current_seq.append(line)
    if current_id is not None:
        sequences.append((current_id, "".join(current_seq)))

    json_sequences = []
    for seq_id, seq in sequences:
        match = rx.search(seq_id)
        entity_type = match.group(1).lower() if match else "protein"

        if entity_type not in ENTITY_TYPES:
            raise ValueError(
                f"Invalid entity type: {entity_type}. Must be one of {ENTITY_TYPES}"
            )

        protenix_type = ENTITY_TYPE_MAP[entity_type]

        if entity_type == "ligand":
            entity = {protenix_type: {"ligand": seq, "count": 1}}
        else:
            entity = {protenix_type: {"sequence": seq, "count": 1}}

        json_sequences.append(entity)

    return json.dumps([{"name": name, "sequences": json_sequences}], indent=2)


def _extract_metrics_from_json(data) -> dict:
    """Pull AF3-shaped metrics out of an arbitrary Protenix confidence JSON.

    Protenix sidecars vary by version; we accept either a dict or a list-of-
    dicts and tolerate the field names we have seen in the wild.
    """
    metrics: dict = {}
    if isinstance(data, list):
        # Some versions emit [{...sample0...}, {...sample1...}]; just look
        # at the first dict-like entry, callers index per-sample separately.
        data = next((x for x in data if isinstance(x, dict)), {})
    if not isinstance(data, dict):
        return metrics

    # Field name aliases observed across Protenix releases.
    aliases = [
        ("ranking_score", "ranking_score"),
        ("ranking_confidence", "ranking_score"),
        ("ptm", "ptm"),
        ("iptm", "iptm"),
        ("plddt", "plddt_mean"),
        ("mean_plddt", "plddt_mean"),
        ("plddt_mean", "plddt_mean"),
        ("complex_plddt", "plddt_mean"),
        ("has_clash", "has_clash"),
    ]
    for k_src, k_dst in aliases:
        if k_src in data and isinstance(data[k_src], (int, float)):
            metrics[k_dst] = float(data[k_src])

    for src_key, dst_key in [
        ("per_chain_ptm", "per_chain_ptm"),
        ("chain_ptm", "per_chain_ptm"),
        ("per_chain_iptm", "per_chain_iptm"),
        ("chain_iptm", "per_chain_iptm"),
        ("per_chain_plddt", "per_chain_plddt"),
        ("chain_plddt", "per_chain_plddt"),
    ]:
        v = data.get(src_key)
        if isinstance(v, dict):
            metrics[dst_key] = {
                str(k): float(val)
                for k, val in v.items()
                if isinstance(val, (int, float))
            }
        elif isinstance(v, list):
            metrics[dst_key] = {
                str(i): float(val)
                for i, val in enumerate(v)
                if isinstance(val, (int, float))
            }
    return metrics


def _summarize_outputs(out_root: Path) -> dict:
    """Walk Protenix output dir and shape it into the AF3 output.json schema.

    Returns a dict matching schemas/output.json:
        {"predictions": [{"structurePath", "seed", "sampleIndex", "metrics"}]}

    Best-effort: structure paths point at .cif files inside the returned
    file bundle. Confidence metrics (ranking_score, ptm, iptm, plddt_mean)
    are pulled from sibling JSON files when Protenix emits them.
    """
    import json
    import re

    cifs = sorted(p for p in out_root.glob("**/*.cif") if p.is_file())
    predictions = []

    # For debugging metric extraction across Protenix versions, log every
    # JSON we see in the output tree exactly once.
    all_jsons = sorted(p for p in out_root.glob("**/*.json") if p.is_file())
    if all_jsons:
        print(f"[summarize] Found {len(all_jsons)} JSON sidecar(s):")
        for j in all_jsons:
            try:
                size = j.stat().st_size
            except OSError:
                size = -1
            print(f"  - {j.relative_to(out_root)} ({size} bytes)")

    for cif in cifs:
        rel = cif.relative_to(out_root)

        # Protenix names samples like .../seed_<N>/predictions/sample_<K>.cif
        seed_match = re.search(r"seed_(\d+)", str(rel))
        sample_match = re.search(r"sample_(\d+)", cif.stem)
        seed_val = int(seed_match.group(1)) if seed_match else 0
        sample_idx = int(sample_match.group(1)) if sample_match else 0

        metrics: dict = {}

        # Candidate paths, in priority order (most specific first):
        candidates = [
            cif.with_suffix(".json"),
            cif.parent / f"{cif.stem}_confidence.json",
            cif.parent / f"{cif.stem}_summary_confidences.json",
            cif.parent / f"{cif.stem}_confidences.json",
            cif.parent / "summary_confidences.json",
            cif.parent.parent / "summary_confidences.json",
        ]
        # Plus any JSON in the same dir that mentions our sample index.
        for j in cif.parent.glob("*.json"):
            if f"sample_{sample_idx}" in j.name and j not in candidates:
                candidates.append(j)
        # Plus a per-seed summary one level up.
        for j in cif.parent.parent.glob("*.json"):
            if "confid" in j.name.lower() and j not in candidates:
                candidates.append(j)

        for cand in candidates:
            if not cand.is_file():
                continue
            try:
                data = json.loads(cand.read_text())
            except Exception:
                continue
            extracted = _extract_metrics_from_json(data)
            if extracted:
                metrics.update(extracted)
                metrics["_metricsSource"] = str(cand.relative_to(out_root))
                break

        predictions.append(
            {
                "structurePath": str(rel),
                "seed": seed_val,
                "sampleIndex": sample_idx,
                "metrics": metrics,
            }
        )

    return {"predictions": predictions}


@app.function(timeout=TIMEOUT * 60, gpu=GPU)
def predict(
    input_str: str,
    input_name: str = "input",
    seeds: str = DEFAULT_SEEDS,
    use_msa: bool = False,
    model_name: str = DEFAULT_MODEL,
) -> dict:
    """Run Protenix and return AF3-shaped output.

    Args:
        input_str: FASTA or native Protenix JSON content.
        input_name: Job name (used in output paths).
        seeds: Comma-separated integer seeds, e.g. "42" or "42,43".
        use_msa: If True, Protenix runs MSA search (slow). Default False.
        model_name: Protenix model id; defaults to the cheap mini variant.

    Returns:
        {
          "summary": {"predictions": [...]},  # matches schemas/output.json
          "files":   [(relative_path, bytes)] # all artifacts (cif, json, ...)
        }
    """
    return _predict_impl(
        input_str=input_str,
        input_name=input_name,
        seeds=seeds,
        use_msa=use_msa,
        model_name=model_name,
    )


def _predict_impl(
    input_str: str,
    input_name: str = "input",
    seeds: str = DEFAULT_SEEDS,
    use_msa: bool = False,
    model_name: str = DEFAULT_MODEL,
) -> dict:
    from subprocess import run
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as in_dir, TemporaryDirectory() as out_dir:
        if input_str.strip().startswith(">"):
            json_str = _fasta_to_json(input_str, name=input_name)
            print("Converted FASTA to Protenix JSON:")
            print(json_str)
        else:
            json_str = input_str

        json_path = Path(in_dir) / "input.json"
        json_path.write_text(json_str)

        print(
            f"Running Protenix model={model_name} seeds={seeds} use_msa={use_msa}"
        )

        run(
            f'protenix pred --input "{json_path}" '
            f'--out_dir "{out_dir}" '
            f"--seeds {seeds} "
            f"--use_msa {str(use_msa).lower()} "
            f"--model_name {model_name} "
            f"--enable_cache true --enable_fusion true",
            shell=True,
            check=True,
        )

        out_root = Path(out_dir)
        files = [
            (str(p.relative_to(out_root)), p.read_bytes())
            for p in out_root.glob("**/*")
            if p.is_file()
        ]
        summary = _summarize_outputs(out_root)
        return {"summary": summary, "files": files}


def _chains_to_fasta(chains: list[dict]) -> str:
    lines: list[str] = []
    for chain in chains:
        chain_id = str(chain.get("id", "A"))
        sequence = str(chain.get("sequence", ""))
        if not sequence:
            continue
        entity = "protein"
        if chain_id.startswith("dna:"):
            entity = "dna"
            chain_id = chain_id[4:]
        elif chain_id.startswith("rna:"):
            entity = "rna"
            chain_id = chain_id[4:]
        lines.append(f">{entity}|{chain_id}")
        lines.append(sequence)
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
    selected_chain: str | None = wanted
    seen: set[tuple[str, str, str]] = set()
    sequence: list[str] = []
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
    uploads = internal.get("artifactUploads") if isinstance(internal, dict) else None
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


def _numeric_metrics(metrics: dict) -> dict:
    return {k: v for k, v in metrics.items() if isinstance(v, (int, float))}


def _emit_event(event: dict) -> None:
    print(json.dumps(event), flush=True)


def _classify_error(e: BaseException) -> str:
    """Classify an exception for the error event `code` field.

    Same pattern as boltz2/chai1: maps exceptions to one of
    OOM / TIMEOUT / INVALID_INPUT / INFRA_ERROR / RUNTIME_ERROR.
    """
    msg = str(e).lower()
    if "cuda out of memory" in msg or "cuda oom" in msg or "out of memory" in msg:
        return "OOM"
    if isinstance(e, TimeoutError) or "timeout" in msg or "timed out" in msg:
        return "TIMEOUT"
    if isinstance(e, ValueError):
        return "INVALID_INPUT"
    if isinstance(e, (ConnectionError, OSError)):
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


def _resolve_input_str(merged: dict, params: dict) -> str:
    """Build the Protenix input FASTA from merged params.

    - An explicit `chains` list is rendered via `_chains_to_fasta`.
    - A two-structure co-fold (target + partner) renders a 2-chain FASTA when
      both a target and a partner sequence are resolvable. Target comes from
      sequence/targetSeq/targetPdb (honoring targetChain); partner from
      partnerSeq/partner_seq/partnerPdb (honoring partnerChain).
    - Otherwise a single target FASTA is used, or SMOKE_FASTA when absent.
    """
    chains = merged.get("chains")
    if isinstance(chains, list):
        return _chains_to_fasta(chains)

    internal = merged.get("_papercrane") if isinstance(merged.get("_papercrane"), dict) else {}
    target_ref = merged.get("targetPdb") or params.get("targetPdb")
    target_seq = (
        merged.get("sequence")
        or merged.get("targetSeq")
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
    partner_ref = merged.get("partnerPdb") or params.get("partnerPdb")
    partner_seq = (
        merged.get("partnerSeq")
        or merged.get("partner_seq")
        or _sequence_from_pdb(
            partner_ref,
            merged.get("partnerChain"),
        )
    )
    if not partner_seq and internal.get("partnerStructureUrl"):
        partner_seq = _sequence_from_structure_url(
            internal.get("partnerStructureUrl"), merged.get("partnerChain")
        )
    if not partner_seq and partner_ref:
        raise ValueError(f"could not resolve partner {partner_ref!r}")
    if target_seq and partner_seq:
        return _chains_to_fasta([
            {"id": "A", "sequence": str(target_seq)},
            {"id": "B", "sequence": str(partner_seq)},
        ])

    return f">protein|A\n{target_seq}\n" if target_seq else SMOKE_FASTA


@app.function(timeout=TIMEOUT * 60, gpu=GPU)
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
    input_str = _resolve_input_str(merged, params)

    model_name = str(merged.get("model_name", merged.get("modelName", DEFAULT_MODEL)))
    use_msa = bool(merged.get("use_msa", merged.get("useMsa", False)))

    completed = 0
    failed_seeds = 0
    for seed in seeds:
        try:
            result = _predict_impl(
                input_str=input_str,
                input_name=job_id,
                seeds=str(int(seed)),
                use_msa=use_msa,
                model_name=model_name,
            )
        except Exception as e:
            code = _classify_error(e)
            _emit_event({
                "type": "error",
                "seed": int(seed),
                "code": code,
                "message": str(e)[:500],
                "retryable": code in ("OOM", "TIMEOUT", "INFRA_ERROR"),
            })
            failed_seeds += 1
            # Continue — other seeds may succeed.
            continue

        predictions = result.get("summary", {}).get("predictions", []) or []
        if not predictions:
            # No structures produced for this seed — surface as an error event
            # so the worker doesn't silently report success.
            _emit_event({
                "type": "error",
                "seed": int(seed),
                "code": "RUNTIME_ERROR",
                "message": "Protenix produced no predictions for seed",
                "retryable": False,
            })
            failed_seeds += 1
            continue

        # Protenix may emit multiple samples per seed; report the first sample
        # as the canonical artifact for this seed (matches boltz2/chai1 shape).
        prediction = predictions[0]
        structure_path = prediction.get("structurePath", "prediction.cif")
        structure_bytes = next(
            (
                content
                for path, content in result.get("files", [])
                if path == structure_path or Path(path).name == Path(structure_path).name
            ),
            None,
        )
        if not structure_bytes:
            _emit_event({
                "type": "error",
                "seed": int(seed),
                "code": "RUNTIME_ERROR",
                "message": "Protenix structure bytes were not found in the output bundle",
                "retryable": False,
            })
            failed_seeds += 1
            continue
        artifact_key = _upload_structure(merged, int(seed), structure_bytes)
        _emit_event({
            "type": "seed",
            "seed": int(seed),
            "artifactKey": artifact_key or f"modal/{job_id}/alphafold3/{seed}/{structure_path}",
            "metrics": _numeric_metrics(prediction.get("metrics") or {}),
        })
        completed += 1

    summary = {"tool": "alphafold3", "completed": completed, "failed_seeds": failed_seeds}
    _emit_event({"type": "done", "summary": summary, "failed_seeds": failed_seeds})
    return summary


@app.local_entrypoint()
def main():
    """Smoke test: ubiquitin chain A, mini model, single seed, no MSA."""
    ubiquitin_a = (
        ">protein|A\n"
        "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG\n"
    )

    result = predict.remote(
        input_str=ubiquitin_a,
        input_name="ubiquitin_smoke",
        seeds="42",
        use_msa=False,
        model_name=DEFAULT_MODEL,
    )

    summary = result["summary"]
    files = result["files"]

    cif_files = [name for name, _ in files if name.endswith(".cif")]
    json_files = [name for name, _ in files if name.endswith(".json")]
    print(f"Returned {len(files)} files; {len(cif_files)} mmCIF structures, "
          f"{len(json_files)} JSON sidecars")
    if cif_files:
        print("CIF files:")
        for name in cif_files[:10]:
            size = next((len(b) for n, b in files if n == name), 0)
            print(f"  - {name} ({size} bytes)")
    if json_files:
        print("JSON files:")
        for name in json_files[:10]:
            print(f"  - {name}")

    preds = summary.get("predictions", [])
    print(f"Predictions: {len(preds)}")
    for i, pred in enumerate(preds[:5]):
        print(
            f"  [{i}] seed={pred['seed']} sample={pred.get('sampleIndex')} "
            f"path={pred['structurePath']} metrics={pred['metrics']}"
        )

    if not cif_files:
        raise SystemExit("No mmCIF structures produced — smoke test FAILED")
    metrics_seen = any(
        any(k for k in (p.get("metrics") or {}) if not k.startswith("_"))
        for p in preds
    )
    if metrics_seen:
        print("Smoke test OK: structure + confidence metrics produced.")
    else:
        print("Smoke test OK: structure produced (no metrics extracted yet).")
