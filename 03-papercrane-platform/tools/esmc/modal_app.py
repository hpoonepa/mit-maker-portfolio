# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "modal>=1.0",
# ]
# ///
"""Paper Crane ESM-C 300M Modal app.

Cheap pseudo-log-likelihood (PLL) filter for ranking designed sequences by
sequence plausibility before paying for structure prediction. ESM-C is
EvolutionaryScale's successor to ESM-2 — newer, stronger, same output kinds
(embeddings + pLL). The 300M tier ships under the commercial-clean Cambrian
Open License.

- Weights load from the HuggingFace repo `EvolutionaryScale/esmc-300m-2024-12`.
  (In production ESM-C is canonically loaded via the EvolutionaryScale `esm`
  SDK — https://github.com/evolutionaryscale/esm — but the wire contract here
  mirrors the ESM-2 transformers path exactly.) Default is `esmc_300m`.
- Cached weights live in the modal volume `papercrane-esmc-cache`.
- GPU defaults to A10 (cheap; ESM-C 300M fits in ~8-16GB with headroom for the
  600M tier); override via `GPU=...` env.
- Deterministic per sequence: ESM-C inference has no RNG, so we map the
  Paper Crane `seed` field to the sequence index (`seq[i]`) for record-keying
  parity with the design tools.

Single function: `predict(sequences=..., model_size="300M", ...)` returns
per-sequence metrics + (optionally) pooled embeddings. The worker-facing
`papercrane_dispatch(job_id, seeds, params, prev_output)` is the entrypoint
`apps/worker/src/adapters/_modalRunner.ts` calls.

NDJSON event shape (one per sequence):
    {"type":"seed","seed":N,"metrics":{"pll_mean":..., "pll_sum":...,
     "pll_min":..., "ppl":..., "mean_plddt":..., "seq_len":...},
     "sequence":"...","artifactKey":"modal/<job>/esmc/<seed>/scores.json"}

Test:
    modal run tools/esmc/modal_app.py
"""
from __future__ import annotations

import os
import json
from pathlib import Path

import modal

GPU = os.environ.get("GPU", "A10G")
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", 30))

# Pinned for reproducibility — must match transformers' ESM-C tokenizer.
TRANSFORMERS_VERSION = "4.46.3"
TORCH_VERSION = "2.4.1"

# Public HF checkpoints. Keep this in sync with the tier list in the worker.
MODEL_REPOS: dict[str, str] = {
    "300M": "EvolutionaryScale/esmc-300m-2024-12",
    "600M": "EvolutionaryScale/esmc-600m-2024-12",
}

DEFAULT_MODEL_SIZE = "300M"

ESMC_VOLUME_NAME = "papercrane-esmc-cache"
ESMC_VOLUME = modal.Volume.from_name(ESMC_VOLUME_NAME, create_if_missing=True)
CACHE_DIR = f"/{ESMC_VOLUME_NAME}"

# Smoke-test sequence: ubiquitin chain A (76 aa). Matches the chai1/boltz2 apps.
SMOKE_SEQUENCE = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"


def _prefetch_default_model() -> None:
    """Pre-pull the 300M weights into the volume so the first real run is fast.

    Larger sizes (600M) download on demand in `_predict_impl`.
    """
    import os as _os
    _os.environ.setdefault("HF_HOME", CACHE_DIR)
    _os.environ.setdefault("TRANSFORMERS_CACHE", CACHE_DIR)
    from transformers import AutoTokenizer, AutoModelForMaskedLM

    repo = MODEL_REPOS[DEFAULT_MODEL_SIZE]
    print(f"Prefetching {repo} into {CACHE_DIR} ...")
    AutoTokenizer.from_pretrained(repo, cache_dir=CACHE_DIR)
    AutoModelForMaskedLM.from_pretrained(repo, cache_dir=CACHE_DIR)
    print("Done.")


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .pip_install(
        f"torch=={TORCH_VERSION}",
        f"transformers=={TRANSFORMERS_VERSION}",
        "tokenizers>=0.20,<0.21",
        "numpy",
        "huggingface_hub>=0.24",
        "safetensors",
        "accelerate>=0.34",
    )
    .env({
        "HF_HOME": CACHE_DIR,
        "TRANSFORMERS_CACHE": CACHE_DIR,
        # Stop transformers from chattering on stdout — we own stdout for NDJSON.
        "TRANSFORMERS_VERBOSITY": "error",
        "TOKENIZERS_PARALLELISM": "false",
    })
    .run_function(
        _prefetch_default_model,
        gpu="a10g",
        volumes={CACHE_DIR: ESMC_VOLUME},
    )
)

app = modal.App("papercrane-esmc", image=image)


# ------------------------- core inference ------------------------- #

_MODEL_CACHE: dict[str, tuple] = {}  # keyed by model_size -> (tokenizer, model, device)


def _load_model(model_size: str):
    """Lazy-load + in-process cache the ESM-C model. One per container."""
    import torch
    from transformers import AutoTokenizer, AutoModelForMaskedLM

    size = (model_size or DEFAULT_MODEL_SIZE).upper().replace("B", "B").replace("M", "M")
    if size not in MODEL_REPOS:
        raise ValueError(
            f"unknown model_size {model_size!r}; expected one of {sorted(MODEL_REPOS)}"
        )

    if size in _MODEL_CACHE:
        return _MODEL_CACHE[size]

    repo = MODEL_REPOS[size]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    tokenizer = AutoTokenizer.from_pretrained(repo, cache_dir=CACHE_DIR)
    # 600M benefits from fp16 on A10/A100; 300M runs fp32 fine.
    dtype = torch.float16 if size in {"600M"} else torch.float32
    model = AutoModelForMaskedLM.from_pretrained(
        repo, cache_dir=CACHE_DIR, torch_dtype=dtype
    )
    model.eval()
    model.to(device)

    _MODEL_CACHE[size] = (tokenizer, model, device)
    return tokenizer, model, device


def _score_sequence(sequence: str, tokenizer, model, device) -> dict:
    """Compute per-residue pseudo-log-likelihood via masked-token approximation.

    Strategy (efficient, batched): replace each of the L residues with <mask>
    in turn, run a single forward pass over the L-sized batch, then read off
    the log-prob of the true token at each masked position. This is the
    standard PLL formulation used in ESM zero-shot variant effect work.

    For long sequences we chunk the L copies into mini-batches sized to the
    available GPU memory. Returns:
        {pll_mean, pll_sum, pll_min, pll_max, pll_std, ppl,
         mean_plddt, per_residue_pll: [...], seq_len}

    `mean_plddt` here is a sigmoid-mapped pLL surrogate in [0, 100], NOT a
    structural pLDDT. It exists for downstream filters that expect a 0-100
    "confidence" axis — see ESM's README on using -pLL as a plausibility
    proxy for designed sequences.
    """
    import math
    import torch

    seq = sequence.upper().strip()
    if not seq:
        raise ValueError("empty sequence")

    # Tokenize once to get the true token ids and the <mask> id.
    enc = tokenizer(seq, return_tensors="pt", add_special_tokens=True)
    input_ids = enc["input_ids"].to(device)            # [1, L+2] (CLS, ..., EOS)
    attn = enc["attention_mask"].to(device)
    mask_id = tokenizer.mask_token_id
    if mask_id is None:
        raise RuntimeError("ESM-C tokenizer is missing a mask token")

    # Indices of the *residue* tokens (skip CLS at 0 and EOS at -1).
    L = input_ids.shape[1] - 2
    if L <= 0:
        raise ValueError("sequence too short after tokenization")

    # Build the [L, L+2] batch where row i has position (i+1) replaced by <mask>.
    base = input_ids.repeat(L, 1)                       # [L, L+2]
    targets = base[torch.arange(L), torch.arange(L) + 1].clone()  # [L]
    base[torch.arange(L), torch.arange(L) + 1] = mask_id
    attn_b = attn.repeat(L, 1)

    # Mini-batch to keep memory bounded. 16 is safe on A10 for L<=1024 on 300M.
    batch_size = max(1, int(os.environ.get("ESMC_BATCH", "16")))
    per_residue_logp: list[float] = []

    with torch.inference_mode():
        for start in range(0, L, batch_size):
            end = min(start + batch_size, L)
            chunk_ids = base[start:end]
            chunk_attn = attn_b[start:end]
            out = model(input_ids=chunk_ids, attention_mask=chunk_attn)
            # logits: [B, L+2, V]; we only care about the masked positions,
            # which are at column (start..end)+1 within row r of this chunk.
            logits = out.logits.float()
            log_probs = torch.log_softmax(logits, dim=-1)
            rows = torch.arange(end - start, device=device)
            cols = torch.arange(start, end, device=device) + 1
            tgt = targets[start:end].to(device)
            picked = log_probs[rows, cols, tgt]         # [B]
            per_residue_logp.extend([float(x) for x in picked.detach().cpu().tolist()])

    import statistics as _st
    pll_mean = sum(per_residue_logp) / L
    pll_sum = float(sum(per_residue_logp))
    pll_min = float(min(per_residue_logp))
    pll_max = float(max(per_residue_logp))
    pll_std = float(_st.pstdev(per_residue_logp)) if L > 1 else 0.0
    ppl = float(math.exp(-pll_mean))

    # Sigmoid-mapped 0..100 surrogate so the worker can colour-grade like pLDDT.
    # pll_mean is typically in [-6, 0]; map -6 -> ~0, 0 -> ~100 with a soft S.
    surrogate = 100.0 / (1.0 + math.exp(-(pll_mean + 3.0)))

    return {
        "pll_mean": pll_mean,
        "pll_sum": pll_sum,
        "pll_min": pll_min,
        "pll_max": pll_max,
        "pll_std": pll_std,
        "ppl": ppl,
        "mean_plddt": surrogate,
        "per_residue_pll": per_residue_logp,
        "seq_len": L,
    }


def _embed_sequence(sequence: str, tokenizer, model, device, layer: int, pool: str):
    """Extract hidden states from `layer`, optionally pooled."""
    import torch
    import numpy as np

    enc = tokenizer(sequence.upper().strip(), return_tensors="pt", add_special_tokens=True)
    input_ids = enc["input_ids"].to(device)
    attn = enc["attention_mask"].to(device)

    with torch.inference_mode():
        out = model(
            input_ids=input_ids,
            attention_mask=attn,
            output_hidden_states=True,
        )

    hidden = out.hidden_states[layer][0]               # [L+2, D]
    # Drop CLS (idx 0) and EOS (last); keep just the residue positions.
    residues = hidden[1:-1].detach().to(torch.float32).cpu().numpy()  # [L, D]

    if pool == "mean":
        emb = residues.mean(axis=0, keepdims=True)     # [1, D]
    elif pool == "cls":
        emb = hidden[0:1].detach().to(torch.float32).cpu().numpy()  # [1, D]
    elif pool == "none":
        emb = residues
    else:
        raise ValueError(f"unknown pool {pool!r}; expected mean|cls|none")

    return emb


# ------------------------- predict entrypoint ------------------------- #


@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    volumes={CACHE_DIR: ESMC_VOLUME},
)
def predict(
    sequences: list[dict] | list[str] | None = None,
    sequence: str | None = None,
    model_size: str = DEFAULT_MODEL_SIZE,
    mode: str = "score",
    pool: str = "mean",
    layer: int = 30,
) -> dict:
    """Score (or embed) one or more sequences with ESM-C.

    Args:
        sequences: List of {"id": str, "sequence": str} dicts OR a list of bare
            sequence strings. If only `sequence` is provided, it's wrapped into
            a single-record list with id="seq0".
        sequence: Single-sequence convenience for smoke tests.
        model_size: One of {"300M","600M"}. Default 300M.
        mode: "score" (PLL metrics) or "embed" (hidden states).
        pool: Embedding pooling ("mean" | "cls" | "none"). Embed mode only.
        layer: Transformer layer to extract embeddings from. 30 = last layer of
            esmc-300m-2024-12; choose appropriately for other sizes.

    Returns:
        {model, mode, results: [{id, seed, sequence, metrics, embedding?}, ...]}
    """
    return _predict_impl(
        sequences=sequences,
        sequence=sequence,
        model_size=model_size,
        mode=mode,
        pool=pool,
        layer=layer,
    )


def _normalize_sequences(
    sequences: list[dict] | list[str] | None,
    sequence: str | None,
) -> list[dict]:
    if sequences:
        out: list[dict] = []
        for i, s in enumerate(sequences):
            if isinstance(s, dict):
                sid = str(s.get("id") or f"seq{i}")
                seq = str(s.get("sequence") or "")
            else:
                sid = f"seq{i}"
                seq = str(s)
            if not seq:
                continue
            out.append({"id": sid, "sequence": seq})
        if out:
            return out
    if sequence:
        return [{"id": "seq0", "sequence": str(sequence)}]
    return []


def _predict_impl(
    sequences: list[dict] | list[str] | None = None,
    sequence: str | None = None,
    model_size: str = DEFAULT_MODEL_SIZE,
    mode: str = "score",
    pool: str = "mean",
    layer: int = 30,
) -> dict:
    records = _normalize_sequences(sequences, sequence)
    if not records:
        raise ValueError("no sequences provided; pass `sequences=[...]` or `sequence=...`")

    if mode not in {"score", "embed"}:
        raise ValueError(f"mode must be 'score' or 'embed', got {mode!r}")
    if pool not in {"mean", "cls", "none"}:
        raise ValueError(f"pool must be 'mean'|'cls'|'none', got {pool!r}")

    tokenizer, model, device = _load_model(model_size)
    repo = MODEL_REPOS[(model_size or DEFAULT_MODEL_SIZE).upper()]

    results: list[dict] = []
    for idx, rec in enumerate(records):
        seq_id = rec["id"]
        seq = rec["sequence"]

        entry: dict = {
            "id": seq_id,
            "seed": idx,                # deterministic: seed == input index
            "sequence": seq,
            "model": repo,
        }

        if mode == "score":
            entry["metrics"] = _score_sequence(seq, tokenizer, model, device)
        else:  # embed
            emb = _embed_sequence(seq, tokenizer, model, device, layer=layer, pool=pool)
            # Pack the embedding as bytes; the dispatch wrapper writes it to a
            # file under artifactKey. predict() callers get the raw ndarray
            # serialized via numpy savez_compressed for compactness.
            import io
            import numpy as np
            buf = io.BytesIO()
            np.savez_compressed(buf, embedding=emb)
            entry["embedding_npz_bytes"] = buf.getvalue()
            entry["shape"] = list(emb.shape)
            entry["layer"] = int(layer)
            entry["pool"] = pool
            # Also surface a minimal `metrics` block so downstream filters
            # treating ESM-C as just-another-tool don't crash.
            entry["metrics"] = {
                "seq_len": int(emb.shape[0]) if pool == "none" else len(seq),
                "embedding_dim": int(emb.shape[-1]),
            }

        results.append(entry)

    return {
        "model": repo,
        "model_size": (model_size or DEFAULT_MODEL_SIZE).upper(),
        "mode": mode,
        "pool": pool if mode == "embed" else None,
        "layer": layer if mode == "embed" else None,
        "results": results,
    }


# ------------------------- worker dispatch ------------------------- #


def _numeric_metrics(metrics: dict) -> dict:
    """Strip non-scalar fields (e.g. per_residue_pll list) for the NDJSON event."""
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


def _resolve_sequences(merged: dict, prev_output: dict | None) -> list[dict]:
    """Pull sequences from params, falling back to prevOutput.designs[].sequence.

    Order of precedence:
      1. params.sequences (list[{id, sequence}] or list[str])
      2. params.sequence (single string)
      3. prev_output.designs[].sequence (chained from ProteinMPNN / BindCraft)
      4. SMOKE_SEQUENCE
    """
    direct = merged.get("sequences")
    if isinstance(direct, list) and direct:
        return _normalize_sequences(direct, None)

    single = merged.get("sequence") or merged.get("binderSeq") or merged.get("binder_seq")
    if isinstance(single, str) and single.strip():
        return [{"id": "seq0", "sequence": single.strip()}]

    if isinstance(prev_output, dict):
        designs = prev_output.get("designs")
        if isinstance(designs, list) and designs:
            out: list[dict] = []
            for i, d in enumerate(designs):
                if not isinstance(d, dict):
                    continue
                seq = d.get("sequence")
                if not seq:
                    continue
                sid = str(d.get("id") or d.get("designId") or f"design{i}")
                out.append({"id": sid, "sequence": str(seq)})
            if out:
                return out

    return [{"id": "smoke", "sequence": SMOKE_SEQUENCE}]


@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    volumes={CACHE_DIR: ESMC_VOLUME},
)
def papercrane_dispatch(
    job_id: str,
    seeds,
    params=None,
    prev_output=None,
) -> dict:
    """Worker-facing NDJSON entrypoint.

    ESM-C doesn't have a real seed axis (deterministic given the weights), so
    ESM-C is deterministic, so seeds select input records rather than model
    randomness. Emit exactly one result for every requested seed; this keeps
    pooled worker lanes idempotent and cycles through multiple input records.
    """
    seeds = _json_arg(seeds, [])
    params = _json_arg(params, {}) or {}
    prev_output = _json_arg(prev_output, None)
    tool_params = params.get("toolParams") if isinstance(params.get("toolParams"), dict) else {}
    merged = {**params, **tool_params}

    records = _resolve_sequences(merged, prev_output)
    seed_values = [int(seed) for seed in seeds] or list(range(len(records)))
    selected_records = [
        records[((seed - 1) if seed > 0 else seed) % len(records)]
        for seed in seed_values
    ]
    model_size = str(merged.get("model_size") or merged.get("modelSize") or DEFAULT_MODEL_SIZE).upper()
    mode = str(merged.get("mode") or "score").lower()
    pool = str(merged.get("pool") or "mean").lower()
    layer = int(merged.get("layer") or 30)

    result = _predict_impl(
        sequences=selected_records,
        model_size=model_size,
        mode=mode,
        pool=pool,
        layer=layer,
    )

    completed = 0
    for seed, entry in zip(seed_values, result["results"]):
        artifact_name = (
            "scores.json" if mode == "score" else f"{entry['id']}.npz"
        )
        event = {
            "type": "seed",
            "seed": seed,
            "designId": f"{job_id}-{seed}",
            "sequence": entry["sequence"],
            "artifactKey": f"modal/{job_id}/esmc/{seed}/{artifact_name}",
            "metrics": _numeric_metrics(entry.get("metrics") or {}),
        }
        _emit_event(event)
        completed += 1

    summary = {
        "tool": "esmc",
        "model": result["model"],
        "model_size": result["model_size"],
        "mode": mode,
        "completed": completed,
        "total_sequences": len(records),
        "requested_seeds": len(seed_values),
    }
    _emit_event({"type": "done", "summary": summary})
    return summary


# ------------------------- local smoke test ------------------------- #


@app.local_entrypoint()
def main() -> None:
    """Smoke test: score ubiquitin chain A (76 aa) with the default 300M model."""
    print(f"[local] Scoring ubiquitin len={len(SMOKE_SEQUENCE)} with esmc_300m ...")
    result = predict.remote(
        sequences=[{"id": "ubq", "sequence": SMOKE_SEQUENCE}],
        model_size="300M",
        mode="score",
    )
    print(f"[local] model={result['model']} mode={result['mode']} "
          f"results={len(result['results'])}")
    for r in result["results"]:
        m = r["metrics"]
        print(
            f"  id={r['id']} seed={r['seed']} L={m['seq_len']} "
            f"pll_mean={m['pll_mean']:.3f} ppl={m['ppl']:.2f} "
            f"plddt_surrogate={m['mean_plddt']:.1f}"
        )

    if not result["results"]:
        raise SystemExit("FAIL: no results returned")
    print("[local] OK")
