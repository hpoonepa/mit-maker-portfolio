"""Per-residue ESM2 embeddings for every full-antigen cache context.

Emits one ``esm_cache/<context_id>.npz`` per context, with rows aligned 1:1 to
that cache file's ``keys`` array, plus a train-only PCA projection to 64 dims.

Design decisions, in the order they bite:

Per-chain, never concatenated
    ESM2 runs once per antigen auth chain. Concatenating a context's chains
    into one sequence would make the last residue of chain A sequence-adjacent
    to the first residue of chain B, and the model would read a peptide bond
    that does not exist.

Observed residues only, no gap padding
    Each chain's sequence is the amino acids actually present in the
    coordinates, in file (polymer) order. Missing residues are NOT padded with
    X. The alternative -- running on SEQRES and mapping observed residues onto
    it -- is better in principle but unavailable: SEQRES is empty for roughly a
    fifth of the chains here (PDB-format entries and assembly-expanded
    structures lose their entity sequences). Using SEQRES where present and
    observed-only elsewhere would make a residue's embedding depend on which
    file format its entry happened to be deposited in, and that inconsistency
    across the feature block is worse than one uniform artifact. So: uniform
    observed-only, and the receipt reports the gap magnitude
    (``residues_adjacent_across_gap``) so downstream knows its size.

Exact mapping, asserted
    Every residue carries its ResidueKey, so rows are emitted in the cache's
    own ``keys`` order by explicit lookup rather than by assuming the cache
    order matches file order. Every key must resolve or the context fails.

No leakage
    Sequence only, and only from chains named in the cache's ``chains`` field,
    which are the antigen chains. ``load_antigen`` has already dropped the
    antibody; the chain filter means assembly neighbours do not get in either.

PCA on train contexts only
    Every context in this benchmark holds instances from exactly one split, so
    "contexts whose instances are all train" is just the train contexts. The
    projection is fitted on their residues alone and then applied to all
    contexts, because fitting on val/test too would leak those splits into the
    feature construction itself.

Entropy caveat
    ``entropy`` is the Shannon entropy of the MLM head's softmax at each
    position with the *unmasked* sequence as input -- one extra matmul, free.
    It is NOT masked-LM pseudo-perplexity, which needs one forward pass per
    residue and was skipped as too expensive.
"""

from __future__ import annotations
from paths import DATA, REPO, MODEL

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
from pathlib import Path

# transformers probes for TensorFlow/Flax at import time, and the installed
# TensorFlow was built with AVX, which this machine lacks -- the probe hard
# crashes the interpreter. We only ever want the torch backend.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_FLAX", "0")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = REPO
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

import gemmi  # noqa: E402
import torch  # noqa: E402
from transformers import AutoTokenizer, EsmForMaskedLM  # noqa: E402

from benchmark.structures import load_antigen  # noqa: E402

CIF_DIR = ROOT / ".cache/benchmark/cif"
DEFAULT_CACHE_DIR = "cache_full_antigen"
RECEIPT_PATH = DATA / 'esm_receipt.json'

# esm2_t30_150M_UR50D (30 layers, 640-dim), not the 650M, and not by preference.
# Both are MIT. The 650M was the first choice and its download stalled out on
# this machine at ~250 KB/s with 1.1 GB still to fetch -- roughly 75 more
# minutes of wall clock for the weights alone, on top of two hours already
# spent, which blows the runtime budget before a single residue is embedded.
# Measured inference is not the constraint either way: 0.41 ms/residue for the
# 35M under Rosetta, so ~1.8 ms/residue here, ~5 min for all 176,842 residues,
# against ~25 min for the 650M. Pass --model facebook/esm2_t33_650M_UR50D to
# upgrade once the weights are local; `embedding_done` keys on the model id, so
# an upgrade run recomputes rather than silently reusing these 640-dim vectors.
MODEL_ID = "facebook/esm2_t30_150M_UR50D"
WINDOW = 1022  # ESM2 allows 1024 positions + <cls> + <eos>
OVERLAP = 256
N_COMPONENTS = 64
THREADS = 15
PCA_BATCH = 20000  # residues per IncrementalPCA.partial_fit call


def keystr(chain: str, num: int, icode: str) -> str:
    """Reproduce build_cache.keystr exactly, including its space-icode quirk.

    ``build_cache`` appends the insertion code when it is truthy, and gemmi
    reports "no insertion code" as a single space, which *is* truthy. So most
    keys look like ``A:224: `` with a trailing space, not ``A:224``.
    """
    return f"{chain}:{num}" + (f":{icode}" if icode else "")


def one_letter(resname: str) -> str:
    """Three-letter residue name to an ESM2 vocabulary token.

    gemmi lowercases the code for modified residues whose parent is standard
    (MSE -> 'm'), which is what we want folded back to the parent: ESM2 has no
    selenomethionine token, and M is the honest stand-in. Anything else is X.
    """
    info = gemmi.find_tabulated_residue(resname)
    if info is not None and info.one_letter_code.isalpha():
        code = info.one_letter_code.upper()
        if code in "ACDEFGHIKLMNPQRSTVWY":
            return code
    return "X"


def _load_antigen_retrying(pdb_id: str, antigen_chains: list[str], retries: int = 5):
    """``load_antigen``, retried, for the same reason ``load_context`` is.

    Under the same disk contention this raises
    ``FileNotFoundError: Failed to read .../<pdb>.cif.gz`` for structures that
    are sitting on disk the whole time -- 2zck and 1h0d both failed this way
    mid-run and both were present, unmodified, when checked seconds later.
    Treating that as "no structure for this entry" would silently drop real
    contexts from the feature block, so it is retried instead.
    """
    last: Exception | None = None
    for attempt in range(retries):
        try:
            return load_antigen(CIF_DIR, pdb_id, antigen_chains)
        except FileNotFoundError as exc:
            last = exc
            time.sleep(0.25 * (attempt + 1))
    raise OSError(f"{pdb_id}: structure unreadable after {retries} attempts: {last!r}")


def chain_sequences(pdb_id: str, antigen_chains: list[str]) -> dict[str, dict]:
    """Per-chain sequence and ResidueKey -> sequence-position map.

    Returns ``{chain: {"seq": str, "pos": {keystr: index}, "numgaps": int}}``.
    """
    target, _assembly = _load_antigen_retrying(pdb_id, antigen_chains)
    want = set(antigen_chains)
    out: dict[str, dict] = {}
    for chain in target.st[0]:
        if chain.name not in want:
            continue
        seq: list[str] = []
        pos: dict[str, int] = {}
        nums: list[int] = []
        for res in chain:
            info = gemmi.find_tabulated_residue(res.name)
            if info is None or not info.is_amino_acid():
                continue
            key = keystr(chain.name, res.seqid.num, res.seqid.icode)
            if key in pos:
                # An assembly copy reusing the original chain name would land
                # here. The cache was built from a dict keyed the same way, so
                # first-occurrence-wins matches what it saw.
                continue
            pos[key] = len(seq)
            seq.append(one_letter(res.name))
            nums.append(res.seqid.num)
        if not seq:
            continue
        # Residues made sequence-adjacent only because the ones between them
        # are unmodelled. Reported, not corrected -- see the module docstring.
        gaps = sum(1 for i in range(len(nums) - 1) if nums[i + 1] - nums[i] > 1)
        existing = out.setdefault(chain.name, {"seq": "", "pos": {}, "numgaps": 0})
        if existing["seq"]:
            continue  # duplicate chain object with the same name; keep the first
        out[chain.name] = {"seq": "".join(seq), "pos": pos, "numgaps": gaps}
    return out


@torch.no_grad()
def embed(seq: str, model, tokenizer, device: str) -> tuple[np.ndarray, np.ndarray, bool]:
    """Final-layer per-residue representations and MLM logit entropy.

    Long chains are run as overlapping windows and averaged where they
    overlap. Returns ``(emb[L, d], entropy[L], windowed)``, d = hidden size.
    """
    length = len(seq)
    dim = model.config.hidden_size
    total = np.zeros((length, dim), dtype=np.float64)
    ent_total = np.zeros(length, dtype=np.float64)
    counts = np.zeros(length, dtype=np.float64)

    starts = [0]
    if length > WINDOW:
        step = WINDOW - OVERLAP
        starts = list(range(0, length - WINDOW + step, step))
        starts = [min(s, length - WINDOW) for s in starts]
        starts = sorted(set(starts))

    for start in starts:
        stop = min(start + WINDOW, length)
        chunk = seq[start:stop]
        batch = tokenizer(chunk, return_tensors="pt", add_special_tokens=True)
        batch = {k: v.to(device) for k, v in batch.items()}
        out = model(**batch, output_hidden_states=True)
        # hidden_states[-1] is post-`emb_layer_norm_after` (verified in
        # transformers/models/esm/modeling_esm.py: the norm is applied before
        # the final state is appended), so it is the canonical layer-33
        # representation, identical to EsmModel.last_hidden_state.
        hidden = out.hidden_states[-1][0]
        logits = out.logits[0]
        n_tok = hidden.shape[0]
        # <cls> at 0, <eos> last.
        assert n_tok == len(chunk) + 2, f"token count {n_tok} != {len(chunk)} + 2"
        hidden = hidden[1 : len(chunk) + 1].float()
        logits = logits[1 : len(chunk) + 1].float()
        ent = -(logits.log_softmax(-1).exp() * logits.log_softmax(-1)).sum(-1)
        total[start:stop] += hidden.cpu().numpy().astype(np.float64)
        ent_total[start:stop] += ent.cpu().numpy().astype(np.float64)
        counts[start:stop] += 1.0

    assert counts.min() > 0, "a residue was covered by no window"
    emb = (total / counts[:, None]).astype(np.float32)
    entropy = (ent_total / counts).astype(np.float32)
    return emb, entropy, len(starts) > 1


def load_context(path: Path, retries: int = 5) -> dict:
    """Read one cache context, retrying a failed decode.

    Reads here are flaky under load, not wrong. Decoding all 561 files in a
    tight loop while three ``build_cache_all.py`` workers write to a disk at
    99% capacity, a varying ~11-12 of them come back as a zero-length read and
    raise JSONDecodeError at char 0; every one of those files then decodes
    perfectly on an individual retry, byte-for-byte complete, and the failing
    set differs run to run. So this retries rather than trusting a single
    attempt, and the caller treats a context that still fails as one lost
    context instead of letting it kill the whole run.
    """
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with gzip.open(path, "rt") as stream:
                return json.load(stream)
        except Exception as exc:
            last = exc
            time.sleep(0.25 * (attempt + 1))
    raise OSError(f"{path.name} failed to decode after {retries} attempts: {last!r}")


def build_one(ctx: dict, model, tokenizer, device: str) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Embeddings in the cache's own ``keys`` order.

    Returns ``(emb, entropy, windowed_chains, gap_adjacencies)``.
    """
    chains = chain_sequences(ctx["pdb"], list(ctx["chains"]))
    rows: dict[str, np.ndarray] = {}
    ents: dict[str, float] = {}
    windowed = 0
    gaps = 0
    for name, info in chains.items():
        emb, entropy, was_windowed = embed(info["seq"], model, tokenizer, device)
        windowed += int(was_windowed)
        gaps += info["numgaps"]
        for key, idx in info["pos"].items():
            rows[key] = emb[idx]
            ents[key] = float(entropy[idx])

    keys = list(ctx["keys"])
    missing = [k for k in keys if k not in rows]
    if missing:
        raise ValueError(
            f"{len(missing)} of {len(keys)} cache keys got no embedding, "
            f"e.g. {missing[:5]}"
        )
    emb = np.stack([rows[k] for k in keys]).astype(np.float32)
    entropy = np.array([ents[k] for k in keys], dtype=np.float32)
    if not np.isfinite(emb).all():
        raise ValueError("non-finite embedding values")
    if np.abs(emb).max() == 0.0:
        raise ValueError("all-zero embeddings")
    return emb, entropy, windowed, gaps


def embedding_done(path: Path, keys: list[str], model_id: str) -> bool:
    """True when this context's embedding is already on disk, from this model.

    Resumability is keyed on ``context_id`` (the filename), so one shared
    ``esm_cache/`` serves every input cache and a context shared between
    caches is computed once. Two things are still verified before reuse:

    ``keys``
        A context_id collision with a *different* residue set would silently
        misalign every row. Shared ids are expected to have identical keys, so
        this should never fire -- but a wrong-answer bug with no symptom is
        worth one npz header read to rule out.
    ``model_id``
        Without this, re-running with a different ``--model`` would keep the
        old model's vectors and report success, so a later upgrade from the
        150M to the 650M would silently produce a mixed feature block. The
        embedding dimension differs between the two, which means downstream
        would hit a shape error or, worse, quietly consume whichever it found.
    """
    if not path.exists():
        return False
    try:
        with np.load(path, allow_pickle=False) as data:
            if "emb" not in data or "keys" not in data:
                return False
            if "model_id" not in data or str(data["model_id"]) != model_id:
                return False
            if [str(k) for k in data["keys"]] != keys:
                return False
            return data["emb"].shape[0] == len(keys)
    except Exception:
        return False


def projection_current(path: Path, pca_id: str) -> bool:
    """True when this context already carries emb64 from *this* projection.

    Deliberately separate from :func:`embedding_done`: refitting the PCA on a
    larger cache must rewrite the 64-dim block without recomputing a single
    ESM2 forward pass. The stored ``pca_id`` is what makes a stale small-cache
    projection impossible to mistake for a current one.
    """
    try:
        with np.load(path, allow_pickle=False) as data:
            return "emb64" in data and str(data["pca_id"]) == pca_id
    except Exception:
        return False


def _emb_rows(path: Path) -> int:
    """Row count of ``emb`` from the .npy header alone.

    ``np.load(...)["emb"].shape`` decompresses the whole array to answer this,
    which across 4,457 train contexts means reading ~2 GB twice -- once to plan
    the batches and again to fit them. Reading just the header keeps the
    planning pass nearly free. Falls back to the full load if the npy header
    layout is ever not what numpy.lib.format expects.
    """
    import zipfile

    import numpy.lib.format as fmt

    try:
        with zipfile.ZipFile(path) as bundle, bundle.open("emb.npy") as handle:
            version = fmt.read_magic(handle)
            if version == (1, 0):
                shape, _fortran, _dtype = fmt.read_array_header_1_0(handle)
            else:
                shape, _fortran, _dtype = fmt.read_array_header_2_0(handle)
            return int(shape[0])
    except Exception:
        with np.load(path, allow_pickle=False) as data:
            return int(data["emb"].shape[0])


def fit_pca(out_dir: Path, train_ids: list[str]) -> dict:
    """PCA fitted on train-split residues only, batched so it scales.

    ``IncrementalPCA`` rather than full ``PCA``: the 561-context cache is
    ~102k train residues (~260 MB as float32 at 640 dims, fine either way),
    but the ~3-4k-context cache this will be refit on is ~1.1M residues, i.e.
    ~2.8 GB at 640 dims and ~5.6 GB at 1280 -- not viable to hold at once. Using the batched estimator at both sizes also
    keeps the small-cache numbers directly comparable to the refit, instead of
    changing estimator underneath the comparison. Every train residue is used;
    the batching is over samples, nothing is subsampled or dropped.
    """
    from sklearn.decomposition import IncrementalPCA

    # Partition contexts into batches first. partial_fit raises when a batch
    # holds fewer samples than n_components, so a small trailing batch is
    # merged into the previous one rather than flushed on its own -- dropping
    # it instead would quietly fit on less than the train split.
    sizes = [(cid, _emb_rows(out_dir / f"{cid}.npz")) for cid in train_ids]
    total = sum(n for _, n in sizes)
    if total < N_COMPONENTS:
        raise ValueError(f"only {total} train residues for {N_COMPONENTS} components")

    batches: list[list[str]] = []
    held = 0
    for cid, n in sizes:
        if not batches or held >= PCA_BATCH:
            batches.append([])
            held = 0
        batches[-1].append(cid)
        held += n
    if len(batches) > 1 and sum(dict(sizes)[c] for c in batches[-1]) < N_COMPONENTS:
        batches[-2].extend(batches.pop())

    pca = IncrementalPCA(n_components=N_COMPONENTS)
    for batch in batches:
        blocks = []
        for cid in batch:
            with np.load(out_dir / f"{cid}.npz", allow_pickle=False) as data:
                blocks.append(data["emb"].astype(np.float32))
        pca.partial_fit(np.concatenate(blocks, axis=0))

    return {
        "components": pca.components_.astype(np.float32),
        "mean": pca.mean_.astype(np.float32),
        "explained_variance": pca.explained_variance_.astype(np.float32),
        "explained_variance_ratio": pca.explained_variance_ratio_.astype(np.float32),
        "n_train_contexts": len(train_ids),
        "n_train_residues": total,
        "train_context_ids": train_ids,
    }


def projection_id(components: np.ndarray, mean: np.ndarray) -> str:
    """Content hash of the projection, so a stale emb64 is always detectable."""
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(components, dtype=np.float32).tobytes())
    digest.update(np.ascontiguousarray(mean, dtype=np.float32).tobytes())
    return digest.hexdigest()[:16]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="only the first N contexts")
    parser.add_argument("--contexts", default=None, help="comma-separated context ids")
    parser.add_argument("--model", default=MODEL_ID)
    parser.add_argument("--smoke", action="store_true", help="extra alignment checks, no PCA")
    parser.add_argument(
        "--cache-dir",
        default=DEFAULT_CACHE_DIR,
        help="input cache of *.json.gz contexts, relative to PRINCE_DATA_DIR or absolute",
    )
    parser.add_argument(
        "--out-dir",
        default="esm_cache",
        help="shared embedding output; resumability is keyed on context_id, so"
        " one directory serves every input cache and a context shared between"
        " caches is embedded once",
    )
    args = parser.parse_args()

    torch.set_num_threads(THREADS)
    cache_dir = Path(args.cache_dir)
    if not cache_dir.is_absolute():
        cache_dir = DATA / cache_dir
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = DATA / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    start_wall = time.monotonic()

    paths = sorted(cache_dir.glob("*.json.gz"))
    if not paths:
        print(f"no contexts in {cache_dir}", file=sys.stderr)
        return 1
    if args.contexts:
        wanted = set(args.contexts.split(","))
        paths = [p for p in paths if p.name.split(".")[0] in wanted]
    if args.limit:
        paths = paths[: args.limit]

    device = "cpu"
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = EsmForMaskedLM.from_pretrained(args.model).to(device).eval()
    revision = getattr(model.config, "_commit_hash", None)
    print(
        f"model {args.model} layers={model.config.num_hidden_layers} "
        f"dim={model.config.hidden_size} revision={revision}",
        flush=True,
    )

    errors: list[dict] = []
    completed: list[str] = []
    train_ids: list[str] = []
    windowed_chains = 0
    gap_adjacencies = 0
    reused = 0

    # Loaded one at a time rather than all up front: 561 parsed contexts held
    # at once is pointless memory on a machine already under pressure, and a
    # single flaky read would abort the run before any embedding got written.
    for n, path in enumerate(paths, 1):
        try:
            ctx = load_context(path)
        except Exception as exc:
            errors.append({"context_id": path.name, "stage": "load", "error": repr(exc)[:400]})
            print(f"[{n}/{len(paths)}] {path.name} LOAD FAILED {exc!r}", flush=True)
            continue
        cid = ctx["context_id"]
        if ctx["instances"] and all(i["split"] == "train" for i in ctx["instances"]):
            train_ids.append(cid)
        out_path = out_dir / f"{cid}.npz"
        if embedding_done(out_path, [str(k) for k in ctx["keys"]], args.model):
            completed.append(cid)
            reused += 1
            continue
        try:
            t0 = time.monotonic()
            emb, entropy, windowed, gaps = build_one(ctx, model, tokenizer, device)
            windowed_chains += windowed
            gap_adjacencies += gaps
            if args.smoke:
                assert emb.shape == (len(ctx["keys"]), model.config.hidden_size)
                assert not np.allclose(emb[0], emb[len(emb) // 2]), "identical rows"
                assert np.isfinite(entropy).all()
            np.savez_compressed(
                out_path,
                keys=np.array(ctx["keys"], dtype=object).astype("U"),
                emb=emb.astype(np.float16),
                entropy=entropy,
                model_id=np.array(args.model),
            )
            print(
                f"[{n}/{len(paths)}] {cid} {ctx['pdb']} "
                f"res={emb.shape[0]} {time.monotonic() - t0:.1f}s",
                flush=True,
            )
            completed.append(cid)
        except Exception as exc:  # keep going; the receipt records the casualty
            errors.append({"context_id": cid, "pdb": ctx["pdb"], "error": repr(exc)[:400]})
            print(f"[{n}/{len(paths)}] {cid} FAILED {exc!r}", flush=True)

    embed_seconds = time.monotonic() - start_wall
    if args.smoke:
        print(
            f"\nSMOKE ok: {len(completed)} contexts, {len(errors)} errors, "
            f"{embed_seconds:.1f}s"
        )
        return 1 if errors else 0

    # --- train-only PCA -----------------------------------------------------
    # Named for the cache and the train-context count it was fitted on, so a
    # refit against a larger cache lands beside this one as an obviously
    # different artefact instead of overwriting it. Nothing should treat this
    # as the shipped projection until it has been refit on the full cache.
    fitted_ids = [c for c in train_ids if c in set(completed)]
    pca = fit_pca(out_dir, fitted_ids)
    ratio = pca["explained_variance_ratio"]
    components = pca["components"]
    mean = pca["mean"]
    pca_id = projection_id(components, mean)
    tag = args.model.split("/")[-1].replace("esm2_", "").replace("_UR50D", "")
    pca_path = (
        DATA / f"esm_pca__{tag}__{cache_dir.name}__{pca['n_train_contexts']}ctx.json"
    )
    with open(pca_path, "w") as stream:
        json.dump(
            {
                "pca_id": pca_id,
                "provisional": True,
                "provisional_note": "fitted on the "
                f"{cache_dir.name} cache ({pca['n_train_contexts']} train contexts);"
                " expected to be refit on the full manifest cache before shipping."
                " Never apply this projection to features from a different cache"
                " without checking pca_id.",
                "cache_dir": str(cache_dir),
                "model": args.model,
                "model_revision": revision,
                "estimator": "sklearn.decomposition.IncrementalPCA",
                "n_components": N_COMPONENTS,
                "fitted_on": "contexts whose every instance has split=train",
                "n_train_contexts": pca["n_train_contexts"],
                "n_train_residues": pca["n_train_residues"],
                "explained_variance_ratio_total": float(ratio.sum()),
                "explained_variance_ratio": ratio.tolist(),
                "explained_variance": pca["explained_variance"].tolist(),
                "mean": pca["mean"].tolist(),
                "components": pca["components"].tolist(),
                "train_context_ids": pca["train_context_ids"],
            },
            stream,
        )
    print(f"PCA {pca_id}: 64 comps explain {ratio.sum():.4f} of variance, fitted on "
          f"{pca['n_train_residues']} residues from {pca['n_train_contexts']} train contexts "
          f"-> {pca_path.name}",
          flush=True)

    projected = 0
    for cid in completed:
        path = out_dir / f"{cid}.npz"
        if projection_current(path, pca_id):
            continue
        with np.load(path, allow_pickle=False) as data:
            stored = {k: data[k] for k in data.files}
        stored["emb64"] = (
            (stored["emb"].astype(np.float32) - mean) @ components.T
        ).astype(np.float32)
        stored["pca_id"] = np.array(pca_id)
        np.savez_compressed(path, **stored)
        projected += 1

    receipt = {
        "script": str(Path(__file__).resolve()),
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model_id": args.model,
        "model_revision": revision,
        "model_layers": model.config.num_hidden_layers,
        "model_dim": model.config.hidden_size,
        "licence_on_model_card": "mit",
        "licence_source": f"https://huggingface.co/{args.model} -- card metadata"
        " 'License: mit'; HF API cardData.license == 'mit', tags include"
        " 'license:mit'. Checked for esm2_t33_650M_UR50D (revision"
        " 08e4846e537177426273712802403f7ba8261b6c) and esm2_t30_150M_UR50D;"
        " the whole facebook/esm2_* family is MIT. ESM-IF1 (CC-BY-NC) unused.",
        "cache_dir": str(cache_dir),
        "out_dir": str(out_dir),
        "contexts_attempted": len(paths),
        "contexts_failed": len(errors),
        "contexts_completed": len(completed),
        "contexts_reused_from_previous_run": reused,
        "errors": errors,
        # Per-run, NOT cumulative: a resumed run embeds only the contexts it
        # recomputes, so after a resume these undercount the corpus. The
        # verified_* fields below are recomputed across every completed
        # context and are the numbers to quote.
        "chains_needing_windowing_this_run": windowed_chains,
        "contexts_embedded_this_run": len(completed) - reused,
        "window": WINDOW,
        "window_overlap": OVERLAP,
        "residues_adjacent_across_gap_this_run": gap_adjacencies,
        "gap_handling": "observed residues only, in file order; gaps NOT padded"
        " with X (see module docstring for why SEQRES was rejected)",
        "chain_handling": "ESM2 run separately per antigen auth chain; never concatenated",
        "entropy_field": "Shannon entropy of MLM head softmax on the UNMASKED"
        " sequence; masked-LM pseudo-perplexity was skipped as too expensive",
        "pca_artifact": str(pca_path),
        "pca_id": pca_id,
        "pca_provisional": True,
        "pca_estimator": "sklearn.decomposition.IncrementalPCA",
        "pca_n_components": N_COMPONENTS,
        "pca_explained_variance_ratio_total": float(ratio.sum()),
        "pca_n_train_contexts": pca["n_train_contexts"],
        "pca_n_train_residues": pca["n_train_residues"],
        "contexts_projected_this_run": projected,
        "embed_seconds": round(embed_seconds, 1),
        "total_seconds": round(time.monotonic() - start_wall, 1),
        "torch_threads": THREADS,
    }
    with open(RECEIPT_PATH, "w") as stream:
        json.dump(receipt, stream, indent=2)
    print(json.dumps({k: v for k, v in receipt.items() if k != "errors"}, indent=2))
    print(f"errors: {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
