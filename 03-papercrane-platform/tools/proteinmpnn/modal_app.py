# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "modal>=1.0",
# ]
# ///
"""ProteinMPNN Modal app for Paper Crane.

ProteinMPNN (Dauparas et al., 2022) is INVERSE FOLDING: it takes a backbone
(PDB) and designs sequences for it. This is the cheapest tool in the catalog
(A10, ~4s/design) and is the canonical downstream step after any backbone
generator (RFdiffusion, Chroma, BoltzGen).

Pattern mirrors `tools/chai1/modal_app.py` and `tools/boltz2/modal_app.py`:
  - `predict(...)`               clean Python API (used by smoke test + tests)
  - `papercrane_dispatch(...)`   worker-facing NDJSON entrypoint that matches
                                 the `_modalRunner.ts` arg signature

Weights: ProteinMPNN ships with weights checked into the upstream repo
(~6 MB under `/opt/ProteinMPNN/vanilla_model_weights/`), so we do NOT need
to download anything at image-build time.

Test (NOT to be run without Modal credits):
    modal run tools/proteinmpnn/modal_app.py
"""

import os
import io
import json
import re
import urllib.request
from pathlib import Path

import modal

# ------------------------- Image ------------------------- #

GPU = os.environ.get("GPU", "A10")
TIMEOUT_MIN = int(os.environ.get("TIMEOUT", 20))

# Pinned upstream commit (Dauparas et al.). Bump in lockstep with
# tools/proteinmpnn/Dockerfile (the docker build of the same tool).
# 2023-06-27: last commit on `main` (repo has been quiet since; verified via
# `gh api repos/dauparas/ProteinMPNN/commits/main` on 2026-06-02).
PROTEINMPNN_COMMIT = "8907e6671bfbfc92303b5f79c4b5e6ce47cdef57"

# Optional volume for any auxiliary caches the worker chooses to persist.
# ProteinMPNN itself does not need this (weights are in the repo, no
# downloads at runtime), but reserving the mount keeps us symmetric with
# boltz2 and lets ops attach a shared scratch later without redeploys.
MPNN_VOLUME_NAME = "papercrane-mpnn-cache"
MPNN_VOLUME = modal.Volume.from_name(MPNN_VOLUME_NAME, create_if_missing=True)
CACHE_DIR = f"/{MPNN_VOLUME_NAME}"


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "wget", "build-essential")
    .pip_install(
        # ProteinMPNN is a small PyTorch model — any modern torch works.
        # We pin to match the in-repo torch baseline used by other Wave 1
        # tools (chai1 uses chai_lab's own torch pin, boltz2 uses boltz's).
        "torch==2.1.0",
        "numpy==1.26.4",
        "biopython==1.83",
        extra_index_url="https://download.pytorch.org/whl/cu121",
    )
    .run_commands(
        f"git clone https://github.com/dauparas/ProteinMPNN.git /opt/ProteinMPNN "
        f"&& cd /opt/ProteinMPNN && git checkout {PROTEINMPNN_COMMIT}",
    )
)

app = modal.App("papercrane-proteinmpnn", image=image)

# ------------------------- Constants / fixtures ------------------------- #

# Tiny smoke backbone: a 5-residue poly-glycine snippet just so the CLI has
# *something* to chew on when no real backbone is supplied. The local
# entrypoint overrides this with a real PDB fetch.
SMOKE_PDB_ID = "1UBQ"  # ubiquitin
SMOKE_CHAIN = "A"

# Canonical amino-acid alphabet ProteinMPNN designs over (no X).
_AA_ALPHABET = "ACDEFGHIKLMNPQRSTVWY"

# ProteinMPNN FASTA headers look like:
#   >T0, score=1.234, global_score=1.211, fixed_chains=[], designed_chains=['A'], model_name=v_48_020, git_hash=..., seed=42
#   <native sequence>
#   >T=0.1, sample=1, score=1.456, global_score=1.422, seq_recovery=0.412
#   <designed sequence>
_HEADER_KV = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([-0-9.eE+]+)")

# ------------------------- Helpers (pure) ------------------------- #


def _fetch_pdb(pdb_id: str) -> bytes:
    """Fetch a PDB file from RCSB; used by the smoke test only."""
    url = f"https://files.rcsb.org/download/{pdb_id.upper()}.pdb"
    return urllib.request.urlopen(url, timeout=20).read()


def _resolve_backbone_bytes(backbone: object) -> tuple[str, bytes] | None:
    """Resolve a `backbones[i]` entry into (filename, pdb_bytes).

    Accepts:
      - dict {"name": "...", "pdb": "ATOM ..." | b"ATOM ..."}
      - dict {"name": "...", "uri": "http(s)://..."} (fetched live)
      - dict {"name": "...", "pdbId": "1UBQ"}
      - str  raw PDB text starting with "ATOM " / "HEADER" / "MODEL"
      - str  4-letter PDB id (e.g. "1UBQ")
      - str  http(s)://... URL
      - str  s3:// URI -> SKIPPED (worker is responsible for pre-staging
              S3-backed backbones; we can't reach R2/S3 from inside Modal
              without credentials)
    Returns None on unrecognized / unfetchable inputs.
    """
    if isinstance(backbone, dict):
        name = str(backbone.get("name") or backbone.get("id") or "backbone")
        if "pdb" in backbone and backbone["pdb"]:
            data = backbone["pdb"]
            if isinstance(data, str):
                data = data.encode("utf-8")
            return (f"{name}.pdb", data)
        if "uri" in backbone and isinstance(backbone["uri"], str):
            return _resolve_backbone_bytes(backbone["uri"])
        if "pdbId" in backbone and isinstance(backbone["pdbId"], str):
            try:
                return (f"{name}.pdb", _fetch_pdb(backbone["pdbId"]))
            except Exception as exc:
                print(f"Could not fetch PDB {backbone['pdbId']}: {exc}")
                return None
        return None

    if isinstance(backbone, str):
        stripped = backbone.strip()
        # Raw PDB text
        if stripped.startswith(("ATOM ", "HEADER", "MODEL", "REMARK", "HETATM")):
            return ("backbone.pdb", stripped.encode("utf-8"))
        # HTTP(S) URL
        if stripped.startswith(("http://", "https://")):
            try:
                data = urllib.request.urlopen(stripped, timeout=30).read()
            except Exception as exc:
                print(f"Could not fetch backbone {stripped}: {exc}")
                return None
            name = stripped.rsplit("/", 1)[-1] or "backbone.pdb"
            if not name.lower().endswith(".pdb"):
                name = name + ".pdb"
            return (name, data)
        # S3-style URI — worker must pre-stage; skip here.
        if stripped.startswith(("s3://", "r2://", "gs://")):
            print(
                f"Skipping cloud URI backbone (worker should pre-stage): {stripped}"
            )
            return None
        # Bare 4-letter PDB id
        if len(stripped) == 4 and stripped.isalnum():
            try:
                return (f"{stripped.upper()}.pdb", _fetch_pdb(stripped))
            except Exception as exc:
                print(f"Could not fetch PDB {stripped}: {exc}")
                return None

    return None


def _extract_backbones_from_prev(prev_output: object) -> list[dict]:
    """Pull backbone references out of an upstream stage's ToolOutput.

    `prev_output.designs[].structureKey` typically holds a storage key/URI
    for a generated backbone (e.g. RFdiffusion). We pass these through as
    `{"name": ..., "uri": ...}` dicts; `_resolve_backbone_bytes` will only
    successfully resolve http(s) URLs — S3/R2 keys are skipped with a log
    line since the worker should pre-stage those.
    """
    if not isinstance(prev_output, dict):
        return []
    designs = prev_output.get("designs")
    if not isinstance(designs, list):
        return []
    out: list[dict] = []
    for i, d in enumerate(designs):
        if not isinstance(d, dict):
            continue
        key = d.get("structureKey")
        if isinstance(key, str) and key:
            out.append({"name": f"backbone_{i:04d}", "uri": key})
    return out


def _parse_mpnn_fasta(text: str, source_pdb: str) -> list[dict]:
    """Parse a ProteinMPNN `seqs/<pdb>.fa` file into per-design dicts.

    The first record is the NATIVE sequence (skipped). Subsequent records
    are designs with header fields like `T`, `sample`, `score`,
    `global_score`, `seq_recovery`.
    """
    records: list[tuple[str, str]] = []
    header: str | None = None
    body: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header is not None:
                records.append((header, "".join(body)))
            header = line[1:]
            body = []
        else:
            body.append(line)
    if header is not None:
        records.append((header, "".join(body)))

    if not records:
        return []

    designs: list[dict] = []
    # records[0] is native; everything after is a sampled design.
    for sample_idx, (hdr, seq) in enumerate(records[1:], start=1):
        kvs = {k: float(v) for k, v in _HEADER_KV.findall(hdr)}
        clean_seq = "".join(c for c in seq.upper() if c in _AA_ALPHABET)
        metrics: dict[str, float] = {}
        # ProteinMPNN-native numerics — keep them under their canonical names
        # so downstream filters can recognize them across tools.
        if "score" in kvs:
            metrics["score"] = kvs["score"]
            # `score` is per-residue NLL — pseudo-perplexity = exp(score).
            try:
                import math

                metrics["sample_perplexity"] = math.exp(kvs["score"])
            except OverflowError:
                pass
        if "global_score" in kvs:
            metrics["global_score"] = kvs["global_score"]
        if "seq_recovery" in kvs:
            metrics["recovery"] = kvs["seq_recovery"]
        if "T" in kvs:
            metrics["temperature"] = kvs["T"]
        designs.append({
            "sample": int(kvs.get("sample", sample_idx)),
            "source_pdb": source_pdb,
            "sequence": clean_seq,
            "metrics": metrics,
            "header": hdr,
        })
    return designs


def _build_fixed_positions_jsonl(
    fixed_positions: dict | None,
    pdb_stems: list[str],
) -> str | None:
    """ProteinMPNN expects `--fixed_positions_jsonl <path>` with shape:
        {"<pdb_stem>": {"A": [1, 4, 5], "B": []}, ...}
    Build a single JSONL line covering every staged backbone.
    """
    if not fixed_positions:
        return None
    payload = {stem: fixed_positions for stem in pdb_stems}
    return json.dumps(payload)


# ------------------------- Core impl ------------------------- #


def _predict_impl(
    backbones: list[object],
    seeds: list[int],
    *,
    temperature: float = 0.1,
    omit_aas: str = "CX",
    num_seq_per_target: int = 1,
    fixed_positions: dict | None = None,
) -> dict:
    """Run ProteinMPNN over every (backbone × seed) and return parsed designs.

    Returns:
        {
          "backbones": [{"name", "size"}],
          "seeds": [int, ...],
          "results": [
            {"backbone": str, "seed": int,
             "designs": [{"sample", "sequence", "metrics", ...}, ...],
             "fasta_text": str}
          ]
        }
    """
    from subprocess import run
    from tempfile import TemporaryDirectory

    # 1. Stage backbones onto disk inside the worker.
    resolved: list[tuple[str, bytes]] = []
    for b in backbones:
        out = _resolve_backbone_bytes(b)
        if out is not None:
            resolved.append(out)
    if not resolved:
        raise ValueError(
            "No usable backbones — provide raw PDB text, an HTTP URL, "
            "or a 4-letter PDB id. S3/R2 URIs must be pre-staged by the worker."
        )

    with TemporaryDirectory() as pdb_dir, TemporaryDirectory() as out_root:
        pdb_dir_p = Path(pdb_dir)
        for fname, data in resolved:
            (pdb_dir_p / fname).write_bytes(data)

        pdb_stems = [Path(fname).stem for fname, _ in resolved]
        fp_jsonl_text = _build_fixed_positions_jsonl(fixed_positions, pdb_stems)
        fp_path: Path | None = None
        if fp_jsonl_text:
            fp_path = Path(out_root) / "fixed_positions.jsonl"
            fp_path.write_text(fp_jsonl_text + "\n")

        results: list[dict] = []
        for seed in seeds:
            seed_out = Path(out_root) / f"seed_{seed}"
            seed_out.mkdir(parents=True, exist_ok=True)
            # Upstream --pdb_path accepts one file, not a directory.
            for fname, _ in resolved:
                cmd = [
                    "python", "/opt/ProteinMPNN/protein_mpnn_run.py",
                    "--pdb_path", str(pdb_dir_p / fname),
                    "--out_folder", str(seed_out),
                    "--num_seq_per_target", str(int(num_seq_per_target)),
                    "--sampling_temp", str(float(temperature)),
                    "--omit_AAs", str(omit_aas),
                    "--seed", str(int(seed)),
                    # batch_size=1 keeps memory usage tiny on A10. ProteinMPNN
                    # otherwise picks an aggressive batch that can OOM on long
                    # backbones with high num_seq_per_target.
                    "--batch_size", "1",
                ]
                if fp_path is not None:
                    cmd += ["--fixed_positions_jsonl", str(fp_path)]
                print("Running:", " ".join(cmd))
                run(cmd, check=True)
            # Outputs land at <seed_out>/seqs/<pdb_stem>.fa
            seqs_dir = seed_out / "seqs"
            if not seqs_dir.exists():
                raise RuntimeError(
                    f"ProteinMPNN produced no `seqs/` dir under {seed_out}"
                )

            for fa in sorted(seqs_dir.glob("*.fa")):
                stem = fa.stem
                fasta_text = fa.read_text()
                designs = _parse_mpnn_fasta(fasta_text, source_pdb=stem)
                results.append({
                    "backbone": stem,
                    "seed": int(seed),
                    "designs": designs,
                    "fasta_text": fasta_text,
                })

        return {
            "backbones": [
                {"name": fname, "size": len(data)} for fname, data in resolved
            ],
            "seeds": [int(s) for s in seeds],
            "results": results,
        }


# ------------------------- Modal functions ------------------------- #


@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    buffer_containers=1,
    scaledown_window=300,
    volumes={CACHE_DIR: MPNN_VOLUME},
)
def predict(
    backbones: list,
    seeds: list,
    temperature: float = 0.1,
    omit_aas: str = "CX",
    num_seq_per_target: int = 1,
    fixed_positions: dict | None = None,
) -> dict:
    """Run ProteinMPNN on a list of backbones × seeds.

    Args:
        backbones: list of backbone specs (see `_resolve_backbone_bytes`).
            Each item may be a raw PDB string, a 4-letter PDB id, an HTTP URL,
            or a dict with `pdb` / `uri` / `pdbId`.
        seeds: list of integer seeds; one ProteinMPNN invocation per seed.
        temperature: sampling temperature (lower = more deterministic).
        omit_aas: single-letter AAs to exclude (default "CX").
        num_seq_per_target: number of designed sequences per backbone per seed.
        fixed_positions: optional {chain: [resi, ...]} map (1-based) of
            positions to keep fixed at their native identity.

    Returns:
        See `_predict_impl`.
    """
    return _predict_impl(
        backbones=backbones,
        seeds=[int(s) for s in seeds],
        temperature=float(temperature),
        omit_aas=str(omit_aas),
        num_seq_per_target=int(num_seq_per_target),
        fixed_positions=fixed_positions,
    )


def _numeric_metrics(metrics: dict) -> dict:
    return {k: v for k, v in (metrics or {}).items() if isinstance(v, (int, float))}


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


@app.function(
    timeout=TIMEOUT_MIN * 60,
    gpu=GPU,
    volumes={CACHE_DIR: MPNN_VOLUME},
)
def papercrane_dispatch(
    job_id: str,
    seeds,
    params=None,
    prev_output=None,
) -> dict:
    """Worker-facing NDJSON entrypoint used by `apps/worker`.

    Matches the `_modalRunner.ts` arg signature exactly:
        --job-id <jobId> --seeds <json> --params <json> [--prev-output <json>]

    NDJSON wire format (one object per line to stdout):
        {"type": "seed", "seed": <int>, "artifactKey": "...",
         "sequence": "...", "metrics": {...}}
        ...
        {"type": "done", "summary": {...}}

    NOTE: For the dispatcher to pick `papercrane_dispatch` (instead of the
    default `predict`), add `proteinmpnn: 'papercrane_dispatch'` to
    `PAPERCRANE_ENTRYPOINTS` in `apps/worker/src/adapters/_modalRunner.ts`.
    Until that's added the runner will call `predict(--json ...)` instead and
    will not get NDJSON events — see the TODO in the assistant report.
    """
    seeds_list = _json_arg(seeds, []) or []
    params_obj = _json_arg(params, {}) or {}
    prev = _json_arg(prev_output, None)

    tool_params = params_obj.get("toolParams") if isinstance(
        params_obj.get("toolParams"), dict
    ) else {}
    merged = {**params_obj, **(tool_params or {})}

    # Resolve backbones: explicit `backbones` param wins, otherwise pull
    # `structureKey`s from the upstream stage's output.
    backbones = merged.get("backbones")
    if not isinstance(backbones, list) or not backbones:
        backbones = _extract_backbones_from_prev(prev)
    if not backbones:
        internal = merged.get("_papercrane")
        staged_url = (
            internal.get("targetStructureUrl") if isinstance(internal, dict) else None
        )
        direct = staged_url or merged.get("targetPdbText") or merged.get("targetPdb")
        if direct:
            backbones = [direct]
    if not backbones:
        raise ValueError("ProteinMPNN requires a backbone PDB or uploaded target")

    temperature = float(merged.get("temperature", 0.1))
    omit_aas = str(merged.get("omit_aas", "CX"))
    num_seq_per_target = int(merged.get("num_seq_per_target", 1))
    fixed_positions = merged.get("fixed_positions")
    if isinstance(fixed_positions, str):
        fixed_positions = _json_arg(fixed_positions, None)

    # A workflow provides one RFdiffusion backbone per seed. Keep those pairs
    # aligned instead of taking the Cartesian product of every seed and every
    # upstream backbone.
    paired_backbones: dict[int, object] = {}
    if isinstance(prev, dict) and isinstance(prev.get("designs"), list):
        for design in prev["designs"]:
            if not isinstance(design, dict) or not design.get("structureKey"):
                continue
            try:
                paired_backbones[int(design.get("seed"))] = {
                    "name": f"backbone_{int(design.get('seed')):04d}",
                    "uri": str(design["structureKey"]),
                }
            except (TypeError, ValueError):
                continue

    normalized_seeds = [int(s) for s in seeds_list]
    if paired_backbones and all(seed in paired_backbones for seed in normalized_seeds):
        combined_results: list[dict] = []
        combined_backbones: list[str] = []
        for seed in normalized_seeds:
            paired = _predict_impl(
                backbones=[paired_backbones[seed]],
                seeds=[seed],
                temperature=temperature,
                omit_aas=omit_aas,
                num_seq_per_target=num_seq_per_target,
                fixed_positions=fixed_positions if isinstance(fixed_positions, dict) else None,
            )
            combined_results.extend(paired.get("results", []))
            combined_backbones.extend(paired.get("backbones", []))
        result = {
            "results": combined_results,
            "backbones": combined_backbones,
            "seeds": normalized_seeds,
        }
    else:
        result = _predict_impl(
            backbones=backbones,
            seeds=normalized_seeds,
            temperature=temperature,
            omit_aas=omit_aas,
            num_seq_per_target=num_seq_per_target,
            fixed_positions=fixed_positions if isinstance(fixed_positions, dict) else None,
        )

    # Group designs back by seed so we emit one event per (seed, backbone, sample).
    # ToolOutput.designs[].seed is required, so we always include `seed`.
    events: list[dict] = []
    completed = 0
    for r in result["results"]:
        seed = int(r["seed"])
        backbone = str(r["backbone"])
        for d in r["designs"]:
            sample = int(d.get("sample", 1))
            # Artifact key: one FASTA per (seed, sample) — designed sequence
            # for this backbone. Worker persists these under jobs/<jobId>/designs/.
            artifact_key = (
                f"jobs/{job_id}/designs/{backbone}.seed{seed}.sample{sample}.fasta"
            )
            event: dict = {
                "type": "seed",
                "seed": seed,
                "designId": f"{job_id}-{backbone}-s{seed}-n{sample}",
                "sequence": d.get("sequence", ""),
                "artifactKey": artifact_key,
                "metrics": _numeric_metrics(d.get("metrics") or {}),
            }
            events.append(event)
            _emit_event(event)
            completed += 1

    summary = {
        "tool": "proteinmpnn",
        "completed": completed,
        "backbones": len(result.get("backbones", [])),
        "seeds": len(result.get("seeds", [])),
    }
    done = {"type": "done", "summary": summary}
    events.append(done)
    _emit_event(done)
    return {"events": events, "summary": summary}


# ------------------------- Local entrypoint (smoke test) ------------------------- #


@app.local_entrypoint()
def main():
    """Smoke test: design 1 sequence for ubiquitin chain A at T=0.1, seed=42.

    Runs on Modal (A10, ~10s incl. cold start). NO MODAL CREDITS will be spent
    unless you actually invoke `modal run tools/proteinmpnn/modal_app.py` —
    importing this file (e.g. for unit tests) does not touch Modal.
    """
    print(f"[local] Submitting ProteinMPNN job: {SMOKE_PDB_ID} chain {SMOKE_CHAIN}, seed=42")
    result = predict.remote(
        backbones=[{"name": "smoke_ubiquitin", "pdbId": SMOKE_PDB_ID}],
        seeds=[42],
        temperature=0.1,
        omit_aas="CX",
        num_seq_per_target=2,
    )

    n_results = len(result.get("results") or [])
    n_designs = sum(len(r.get("designs") or []) for r in result.get("results") or [])
    print(f"[local] backbones={len(result.get('backbones', []))} "
          f"results={n_results} designs={n_designs}")

    if n_designs == 0:
        raise SystemExit("FAIL: ProteinMPNN returned no designs")

    for r in result["results"]:
        for d in r["designs"]:
            print(
                f"  backbone={r['backbone']} seed={r['seed']} "
                f"sample={d.get('sample')} len={len(d.get('sequence', ''))} "
                f"metrics={json.dumps(d.get('metrics', {}))}"
            )
    print("[local] OK")
