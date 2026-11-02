# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "modal>=1.0",
# ]
# ///
"""Chai-1 Modal app for Paper Crane.

Ported from biomodals/modal_chai1.py. Returns a structured dict with metrics
(iptm, ptm, plddt) and the CIF bytes so the worker can persist outputs to the
papercrane wire format (`/outputs/predictions/<seed>/pred.model_idx_<N>.cif`).

Test:
    modal run tools/chai1/modal_app.py
"""

import os
import json
from pathlib import Path

import modal

GPU = os.environ.get("GPU", "A100-80GB")
# 50 seeds × ~130s + warmup ≈ 110 min, 120 min buffer
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", 120))


def _classify_error(e: BaseException) -> str:
    """Classify an exception for the error event `code` field."""
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


def download_models() -> None:
    """Bake Chai-1 weights into the image via a tiny inference run."""
    import torch
    from tempfile import TemporaryDirectory
    from chai_lab.chai1 import run_inference

    with TemporaryDirectory() as td_in, TemporaryDirectory() as td_out:
        with open(f"{td_in}/tmp.faa", "w") as out:
            out.write(
                ">protein|name=pro\nMAWTPLLLLLLSHCTGSLSQPVLTQPTSL\n"
                ">ligand|name=lig\nCC\n"
            )
        _ = run_inference(
            fasta_file=Path(f"{td_in}/tmp.faa"),
            output_dir=Path(f"{td_out}"),
            num_trunk_recycles=1,
            num_diffn_timesteps=10,
            seed=1,
            device=torch.device("cuda:0"),
            use_esm_embeddings=True,
        )


image = (
    modal.Image.debian_slim()
    .apt_install("wget")
    .uv_pip_install("chai_lab==0.6.1")
    .run_function(download_models, gpu="A100-80GB")
)

app = modal.App("chai1", image=image)

SMOKE_SEQUENCE = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"


def _build_fasta(chains: list[dict]) -> str:
    lines: list[str] = []
    for c in chains:
        lines.append(f">protein|name={c['id']}")
        lines.append(c["sequence"])
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


def _resolve_chains(merged: dict, params: dict) -> list[dict]:
    """Build the Chai-1 `chains` list from merged params.

    - An explicit `chains` list is passed through untouched.
    - A two-structure co-fold (target + partner) yields chains A/B when both a
      target and a partner sequence are resolvable. The target comes from
      sequence/targetSeq/targetPdb (honoring targetChain); the partner from
      partnerSeq/partner_seq/partnerPdb (honoring partnerChain).
    - Otherwise a single-chain fallback is used (target or SMOKE_SEQUENCE).
    """
    chains = merged.get("chains")
    if isinstance(chains, list):
        return chains

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
        return [
            {"id": "A", "sequence": str(target_seq)},
            {"id": "B", "sequence": str(partner_seq)},
        ]

    sequence = target_seq or SMOKE_SEQUENCE
    return [{"id": str(merged.get("chainId", "A"))[:1] or "A", "sequence": str(sequence)}]


def _summarize_metrics(out_dir: Path) -> list[dict]:
    """Parse Chai-1 `scores.model_idx_<N>.npz` files into per-model metrics."""
    import json
    import numpy as np

    summaries: list[dict] = []
    # Chai 0.6.x writes scores.model_idx_N.npz alongside pred.model_idx_N.cif.
    for npz in sorted(out_dir.glob("**/scores.model_idx_*.npz")):
        try:
            data = np.load(npz, allow_pickle=False)
            keys = set(data.files)
            metrics: dict = {}
            if "aggregate_score" in keys:
                metrics["aggregate_score"] = float(np.asarray(data["aggregate_score"]).mean())
            if "ptm" in keys:
                metrics["ptm"] = float(np.asarray(data["ptm"]).mean())
            if "iptm" in keys:
                metrics["iptm"] = float(np.asarray(data["iptm"]).mean())
            if "complex_plddt" in keys:
                metrics["plddt_mean"] = float(np.asarray(data["complex_plddt"]).mean()) * 100.0
            elif "plddt" in keys:
                metrics["plddt_mean"] = float(np.asarray(data["plddt"]).mean()) * 100.0
            try:
                model_idx = int(npz.stem.rsplit("_", 1)[1])
            except (IndexError, ValueError):
                model_idx = 0
            summaries.append({
                "model_idx": model_idx,
                "metrics": metrics,
                "scores_file": npz.name,
            })
        except Exception as e:  # pragma: no cover - defensive
            summaries.append({
                "model_idx": -1,
                "metrics": {},
                "error": f"{type(e).__name__}: {e}",
                "scores_file": npz.name,
            })

    # Fallback: some Chai versions emit JSON instead.
    if not summaries:
        for j in sorted(out_dir.glob("**/scores.model_idx_*.json")):
            meta = json.loads(j.read_text())
            try:
                model_idx = int(j.stem.rsplit("_", 1)[1])
            except (IndexError, ValueError):
                model_idx = 0
            summaries.append({
                "model_idx": model_idx,
                "metrics": {
                    "plddt_mean": float(meta.get("plddt_mean", meta.get("plddt", 0.0))),
                    "ptm": float(meta.get("ptm", 0.0)),
                    "iptm": float(meta.get("iptm", 0.0)),
                },
                "scores_file": j.name,
            })
    return summaries


@app.function(timeout=TIMEOUT_MIN * 60, gpu=GPU)
def predict(
    sequence: str | None = None,
    chains: list[dict] | None = None,
    chain_id: str = "A",
    num_trunk_recycles: int = 3,
    num_diffn_timesteps: int = 200,
    seed: int = 42,
    use_esm_embeddings: bool = True,
) -> dict:
    """Run Chai-1 on a sequence (or list of chains) and return metrics + CIFs.

    Args:
        sequence: Single chain protein sequence (alternative to `chains`).
        chains: List of {"id", "sequence"} dicts for multi-chain folding.
        chain_id: Chain id to use when `sequence` is provided.
        num_trunk_recycles: Trunk recycles (Chai default 3).
        num_diffn_timesteps: Diffusion timesteps (Chai default 200).
        seed: Random seed.
        use_esm_embeddings: Use ESM embeddings (faster than MSA).

    Returns:
        dict with:
          seed, num_trunk_recycles, num_diffn_timesteps,
          predictions: [{model_idx, metrics, cif_name, cif_bytes}],
          all_files: [(rel_path, bytes)]   # full Chai output dir for the worker
    """
    return _predict_impl(
        sequence=sequence,
        chains=chains,
        chain_id=chain_id,
        num_trunk_recycles=num_trunk_recycles,
        num_diffn_timesteps=num_diffn_timesteps,
        seed=seed,
        use_esm_embeddings=use_esm_embeddings,
    )


def _predict_impl(
    sequence: str | None = None,
    chains: list[dict] | None = None,
    chain_id: str = "A",
    num_trunk_recycles: int = 3,
    num_diffn_timesteps: int = 200,
    seed: int = 42,
    use_esm_embeddings: bool = True,
) -> dict:
    import torch
    from tempfile import TemporaryDirectory
    from chai_lab.chai1 import run_inference

    if chains is None:
        if sequence is None:
            raise ValueError("Provide either `sequence` or `chains`.")
        chains = [{"id": chain_id, "sequence": sequence}]

    fasta_str = _build_fasta(chains)

    with TemporaryDirectory() as td_in, TemporaryDirectory() as td_out:
        fasta_path = Path(td_in) / "input.fasta"
        fasta_path.write_text(fasta_str)
        out_dir = Path(td_out)

        _ = run_inference(
            fasta_file=fasta_path,
            output_dir=out_dir,
            num_trunk_recycles=num_trunk_recycles,
            num_diffn_timesteps=num_diffn_timesteps,
            seed=seed,
            device=torch.device("cuda:0"),
            use_esm_embeddings=use_esm_embeddings,
        )

        all_files: list[tuple[str, bytes]] = []
        for f in sorted(out_dir.glob("**/*")):
            if f.is_file():
                all_files.append((str(f.relative_to(out_dir)), f.read_bytes()))

        scores = {s["model_idx"]: s for s in _summarize_metrics(out_dir)}
        predictions: list[dict] = []
        for cif in sorted(out_dir.glob("**/pred.model_idx_*.cif")):
            try:
                model_idx = int(cif.stem.rsplit("_", 1)[1])
            except (IndexError, ValueError):
                model_idx = 0
            entry = {
                "model_idx": model_idx,
                "cif_name": cif.name,
                "cif_bytes": cif.read_bytes(),
                "metrics": scores.get(model_idx, {}).get("metrics", {}),
            }
            predictions.append(entry)

        return {
            "seed": seed,
            "num_trunk_recycles": num_trunk_recycles,
            "num_diffn_timesteps": num_diffn_timesteps,
            "chains": chains,
            "predictions": predictions,
            "all_files": all_files,
        }


def _numeric_metrics(metrics: dict) -> dict:
    return {k: v for k, v in metrics.items() if isinstance(v, (int, float))}


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


@app.function(timeout=TIMEOUT_MIN * 60, gpu=GPU)
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
    chains = _resolve_chains(merged, params)

    num_trunk_recycles = int(merged.get("num_trunk_recycles", merged.get("recyclingSteps", 3)))
    num_diffn_timesteps = int(merged.get("num_diffn_timesteps", merged.get("diffusionTimesteps", 200)))
    use_esm_embeddings = bool(merged.get("use_esm_embeddings", merged.get("useMsa", True)))

    completed = 0
    failed_seeds = 0
    for seed in seeds:
        try:
            result = _predict_impl(
                chains=chains,
                num_trunk_recycles=num_trunk_recycles,
                num_diffn_timesteps=num_diffn_timesteps,
                seed=int(seed),
                use_esm_embeddings=use_esm_embeddings,
            )
            prediction = (result.get("predictions") or [{}])[0]
            cif_bytes = prediction.get("cif_bytes")
            if not cif_bytes:
                raise RuntimeError("Chai-1 produced no structure bytes")
            artifact_key = _upload_structure(merged, int(seed), cif_bytes)
            _emit_event({
                "type": "seed",
                "seed": int(seed),
                "artifactKey": artifact_key or f"modal/{job_id}/chai1/{seed}/{prediction.get('cif_name', 'prediction.cif')}",
                "metrics": _numeric_metrics(prediction.get("metrics") or {}),
            })
            completed += 1
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

    summary = {"tool": "chai1", "completed": completed, "failed_seeds": failed_seeds}
    _emit_event({"type": "done", "summary": summary})
    return summary


@app.local_entrypoint()
def main() -> None:
    """Smoke test with a 76-aa ubiquitin sequence."""
    import json

    UBIQUITIN = (
        "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"
    )

    print(f"[local] Submitting Chai-1 job: len={len(UBIQUITIN)} aa, seed=42, "
          f"recycles=1, timesteps=50")
    result = predict.remote(
        sequence=UBIQUITIN,
        chain_id="A",
        num_trunk_recycles=1,
        num_diffn_timesteps=50,
        seed=42,
        use_esm_embeddings=True,
    )

    print(f"[local] seeds={result['seed']} models={len(result['predictions'])} "
          f"files={len(result['all_files'])}")
    for p in result["predictions"]:
        print(f"  model_idx={p['model_idx']} cif={p['cif_name']} "
              f"size={len(p['cif_bytes'])}B metrics={json.dumps(p['metrics'])}")

    if not result["predictions"]:
        raise SystemExit("no predictions returned")

    first = result["predictions"][0]
    head = first["cif_bytes"][:200].decode("utf-8", errors="replace").replace("\n", " | ")
    print(f"[local] first CIF head: {head}")
    print("[local] OK")
