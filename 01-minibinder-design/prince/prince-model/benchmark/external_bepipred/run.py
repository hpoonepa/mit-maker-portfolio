"""Local official BepiPred-3.0 comparison; no uploads or fitting on test labels.

Upstream source/weights stay outside this repository under their academic-only
license. This runner uses their Antigens and BP3EnsemblePredict implementations.
"""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import json
import platform
import sys
import time
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from benchmark.evaluate import _antibody_chains, _split_field
from benchmark.structures import locate_structure, _base_chain_name
from hotspot_preflight.structure import load_target, _icode
from hotspot_preflight.residue import ResidueKey
from hotspot_preflight.checks.assembly import expand_assembly
from hotspot_preflight.checks.sasa import _is_amino_acid, _heavy_atoms
import gemmi

REVISION = "98bedf2471e04766c981585180c20da7961c6804"

def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")

def recover_positions(row: dict, record: dict) -> tuple[list[dict], dict[str, str], str | None]:
    """Uniquely recover explicit identities in legacy feature-row order."""
    canonical = record["id"]
    tokens = [v[0] for v in record["res"]]
    path = locate_structure(ROOT / ".cache/benchmark/cif", row["pdb_id"])
    raw = load_target(path)
    assembly_error = None
    try:
        full = expand_assembly(raw) if raw.st.assemblies else raw.st
    except (RuntimeError, ValueError) as exc:
        full = raw.st
        assembly_error = str(exc)
    keep = set(_split_field(row["antigen_chains"]))
    chains, sequences = [], {}
    for chain in full[0]:
        if chain.name not in keep and _base_chain_name(chain.name) not in keep:
            continue
        residues = [r for r in chain if _is_amino_acid(r) and _heavy_atoms(r)]
        if not residues:
            continue
        sequence = "".join(gemmi.find_tabulated_residue(r.name).one_letter_code.upper() for r in residues)
        keys = [ResidueKey(chain.name, r.seqid.num, _icode(r.seqid.icode)) for r in residues]
        if len(keys) != len(set(keys)):
            raise ValueError(f"duplicate structured identity: {canonical}/{chain.name}")
        seqid = hashlib.sha256(sequence.encode()).hexdigest()
        sequences[seqid] = sequence
        chains.append((seqid, keys))
    @lru_cache(None)
    def match(i, j):
        if i == len(chains):
            return [()] if j == len(tokens) else []
        found = match(i + 1, j)
        keys = [str(k) for k in chains[i][1]]
        if tokens[j:j + len(keys)] == keys:
            found = found + [(i,) + rest for rest in match(i + 1, j + len(keys))]
        return found[:2]
    ways = match(0, 0)
    if len(ways) != 1:
        raise ValueError(f"{canonical}: {len(ways)} ordered identity paths for {len(tokens)} rows")
    positions = []
    for ci in ways[0]:
        seqid, keys = chains[ci]
        for index, key in enumerate(keys):
            positions.append({"sequence_id": seqid, "position_0based": index,
                "author": [key.auth_asym_id, key.auth_seq_id, key.icode],
                "declared_chain": key.auth_asym_id in keep})
    return positions, sequences, assembly_error

def prepare(out):
    model_path = ROOT / "data/eval/prince_connected.json"
    manifest = model_path.with_suffix(".manifest.csv")
    model = json.loads(model_path.read_text())
    with manifest.open() as stream:
        rows = list(csv.DictReader(stream))
    requested = model["split_ids"]["test"]
    selected = [r for r in rows if r["instance_id"] in requested]
    if len(selected) != len(requested):
        raise ValueError("heldout manifest join lost interfaces")
    sources = [ROOT / f"data/eval/features_{s}.jsonl.gz" for s in ("train", "test")]
    features = {}
    for path in sources:
        with gzip.open(path, "rt") as stream:
            for line in stream:
                row = json.loads(line)
                if "res" in row:
                    if row["id"] in features:
                        raise ValueError("duplicate feature ID")
                    features[row["id"]] = row
    sequences, mappings, errors, coordinates = {}, [], [], {}
    for row in selected:
        canonical = f"{row['pdb_id']}:{'+'.join(_antibody_chains(row))}"
        record = features[canonical]
        path = locate_structure(ROOT / ".cache/benchmark/cif", row["pdb_id"])
        coordinates[path.name] = sha(path)
        try:
            positions, recovered_sequences, assembly_error = recover_positions(row, record)
        except ValueError as exc:
            errors.append({"id": canonical, "error": str(exc)})
            continue
        sequences.update(recovered_sequences)
        mappings.append({"id": row["instance_id"], "canonical_id": canonical,
            "cluster": row["cluster_id"], "assembly_error": assembly_error,
            "residues": [{"key": v[0], "label": v[-1], **pos} for v, pos in zip(record["res"], positions)]})
    out.mkdir(parents=True, exist_ok=True)
    save(out / "mapping.json", {"requested_ids": requested, "instances": mappings, "errors": errors,
        "method": "Unique ordered whole-chain token block match against explicit coordinate ResidueKey objects; no token parsing",
        "sources": {str(p.relative_to(ROOT)): sha(p) for p in [model_path, manifest, *sources]},
        "coordinate_sha256": coordinates})
    save(out / "sequences.json", sequences)
    ordered = sorted(sequences, key=lambda k: (len(sequences[k]), k))
    (out / "antigens.fasta").write_text("".join(f">{k}\n{sequences[k]}\n" for k in ordered))
    print(json.dumps({"mapped_interfaces": len(mappings), "errors": errors, "unique_sequences": len(sequences)}, indent=2), flush=True)
    if errors:
        raise ValueError("unresolved mapping; refusing evaluation")

def predict(out, upstream, deps, threads):
    sys.path[:0] = [str(upstream), str(deps)]
    import torch
    from bp3 import bepipred3
    torch.set_num_threads(threads)
    started = time.time()
    # Only scheduling differs: batch size one avoids padding and memory spikes.
    # Every token, ESM operation, classifier weight and ensemble remains upstream.
    class SerialAntigens(bepipred3.Antigens):
        def tuple_generator(self, data, batch_size=10):
            yield from super().tuple_generator(data, batch_size=1)
    checkpoint = Path.home() / ".cache/torch/hub/checkpoints/esm2_t33_650M_UR50D.pt"
    antigens = SerialAntigens(out / "antigens.fasta", out / "esm_encodings",
        add_seq_len=True, run_esm_model_local=str(checkpoint))
    ensemble = bepipred3.BP3EnsemblePredict(antigens, device=torch.device("cpu"))
    if len(ensemble.model_states) != 5:
        raise ValueError("official ensemble must have five folds")
    ensemble.run_bp3_ensemble()
    ensemble.create_csvfile(out)
    predictions = {}
    for accession, sequence, probs in zip(antigens.accs, antigens.seqs, antigens.ensemble_probs):
        scores = torch.mean(torch.stack(probs, axis=1), axis=1).cpu().tolist()
        if len(scores) != len(sequence) or not all(0 <= p <= 1 for p in scores):
            raise ValueError(f"invalid sequence predictions: {accession}")
        predictions[accession] = scores
    save(out / "sequence_predictions.json", predictions)
    save(out / "inference_provenance.json", {
        "upstream": "https://github.com/UberClifford/BepiPred-3.0", "revision": REVISION,
        "model": "BepiPred-3.0 BP3C50IDSeqLenFFNN five-fold ensemble; ESM2 t33 650M UR50D",
        "add_sequence_length": True, "sequence_smoothing": False, "device": "cpu",
        "torch": torch.__version__, "python": sys.version, "platform": platform.platform(),
        "processor": platform.processor(), "threads": threads, "elapsed_seconds": time.time() - started,
        "source_sha256": sha(upstream / "bp3/bepipred3.py"),
        "weight_sha256": {p.name: sha(p) for p in [checkpoint, checkpoint.with_name(checkpoint.stem + "-contact-regression.pt"), *ensemble.model_states]},
        "input_sha256": sha(out / "antigens.fasta"), "runner_sha256": sha(__file__),
        "license": "Upstream academic noncommercial only; code and weights not bundled or relicensed",
        "training_overlap": "BepiPred trained on antibody-antigen PDB structures; upstream training overlap is unknown in this retrospective comparison",
        "input_context": "Observed structure-resolved amino acids per antigen chain; unresolved residues not supplied"})

def evaluate(out: Path) -> None:
    import numpy as np
    from benchmark.manifest import format_residue_key
    from benchmark.metrics import per_residue_auroc, per_residue_auprc
    from scripts.train_ranker import evaluate as aggregate
    artifact = ROOT / "data/eval/prince_connected.json"
    corrected = ROOT / "data/eval/features_corrected.jsonl.gz"
    model = json.loads(artifact.read_text())
    mapping = json.loads((out / "mapping.json").read_text())
    predictions = json.loads((out / "sequence_predictions.json").read_text())
    if mapping["errors"]:
        raise ValueError("mapping errors prevent evaluation")
    requested = model["split_ids"]["test"]
    mapped = {r["id"]: r for r in mapping["instances"]}
    if set(requested) != set(mapped):
        raise ValueError("model test IDs changed; repeat prepare/inference")
    with gzip.open(corrected, "rt") as stream:
        records = {r["id"]: r for r in map(json.loads, stream)}
    matrices, clusters, per_instance, output_rows = {}, {}, [], []
    weights = np.array([model["weights"][k] for k in model["features"]] + [model["intercept"]])
    by_component = defaultdict(list)
    for raw_id in requested:
        entry = mapped[raw_id]
        positions = [p for p in entry["residues"] if p["declared_chain"]]
        record = records[entry["canonical_id"]]
        keys = [format_residue_key(ResidueKey(*p["author"])) for p in positions]
        if keys != [r[0] for r in record["res"]] or len(keys) != len(set(keys)):
            raise ValueError(f"corrected author-identity join differs: {raw_id}")
        if record.get("residue_encoding") != "chain:seq[:icode]":
            raise ValueError("corrected feature encoding is not explicit")
        scores = np.array([predictions[p["sequence_id"]][p["position_0based"]] for p in positions])
        matrix = np.array([r[1:] for r in record["res"]], dtype=float)
        labels = matrix[:, 4].astype(bool)
        if not np.isfinite(scores).all() or set(matrix[:, 4]) != {0., 1.}:
            raise ValueError(f"unevaluable scores/labels: {raw_id}")
        fitted_scores = matrix[:, :4] @ weights[:4] + weights[4]
        metrics = {}
        for name, values in (("bepipred3", scores), ("prince", fitted_scores), ("exposure", matrix[:, 0])):
            metrics[name] = {"auroc": per_residue_auroc(values, labels),
                             "auprc": per_residue_auprc(values, labels)}
        by_component[entry["cluster"]].append(metrics)
        per_instance.append({"id": raw_id, "canonical_id": entry["canonical_id"],
            "cluster": entry["cluster"], "n_residues": len(keys), "n_positive": int(labels.sum()),
            "metrics": metrics})
        output_rows.append({"id": raw_id, "canonical_id": entry["canonical_id"],
            "cluster": entry["cluster"], "residues": [
                {"author": p["author"], "key": key, "sequence_id": p["sequence_id"],
                 "position_0based": p["position_0based"], "label": int(label), "score": float(score)}
                for p, key, label, score in zip(positions, keys, labels, scores)]})
        external_matrix = np.zeros_like(matrix)
        external_matrix[:, 0], external_matrix[:, 4] = scores, matrix[:, 4]
        matrices[raw_id], clusters[raw_id] = external_matrix, entry["cluster"]
    summary = aggregate(matrices, requested, clusters, np.array([1., 0, 0, 0, 0]))
    component_metrics = {
        component: {name: {metric: float(np.mean([v[name][metric] for v in values]))
                          for metric in ("auroc", "auprc")}
                    for name in ("bepipred3", "prince", "exposure")}
        for component, values in by_component.items()}
    paired = {}
    for comparator in ("prince", "exposure"):
        paired[comparator] = {}
        for metric in ("auroc", "auprc"):
            delta = np.array([v["bepipred3"][metric] - v[comparator][metric] for v in component_metrics.values()])
            rng = np.random.default_rng(0)
            boot = [delta[rng.integers(len(delta), size=len(delta))].mean() for _ in range(2000)]
            paired[comparator][metric] = {"bepipred_minus_comparator": float(delta.mean()),
                "paired_component_bootstrap_ci95": np.quantile(boot, [.025, .975]).tolist()}
    with gzip.open(out / "residue_predictions.jsonl.gz", "wt") as stream:
        for row in output_rows:
            stream.write(json.dumps(row, allow_nan=False) + "\n")
    result = {"status": "completed_retrospective_comparison", "model": "BepiPred-3.0",
        "requested_instances": len(requested), "evaluated_instances": len(per_instance),
        "n_components": len(component_metrics), "n_residues": sum(r["n_residues"] for r in per_instance),
        "missing_predictions": 0, "mapping_errors": [], "excluded_interfaces": [],
        "residue_universe": "All cached observed residues on declared original antigen chains; symmetry-copy rows removed by shared corrected feature artifact",
        "summary": summary, "paired_differences": paired, "instances": per_instance,
        "components": component_metrics, "test_ids": requested,
        "sources_sha256": {str(p.relative_to(ROOT)): sha(p) for p in [
            artifact, corrected, out / "mapping.json", out / "sequence_predictions.json", Path(__file__)]},
        "limitations": ["BepiPred training-set overlap with these PDB antigens not established; not pristine external generalization.",
            "Both predictors evaluated retrospectively using identical corrected labels; no comparator tuning or PRINCE fitting used test labels in this run, but upstream BepiPred training overlap is unknown.",
            "Sequence input contains observed structure-resolved amino acids, not complete unresolved polymer sequence.",
            "Metrics characterize residue ranking, not patch proposals or binder design success."]}
    save(out / "comparison.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("instances", "components", "test_ids")}, indent=2))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "predict", "evaluate"])
    parser.add_argument("--out", type=Path, default=ROOT / "data/eval/bepipred_connected")
    parser.add_argument("--upstream", type=Path)
    parser.add_argument("--deps", type=Path, default=Path("/tmp/prince-bepipred-deps"))
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.out)
    elif args.mode == "evaluate":
        evaluate(args.out)
    else:
        predict(args.out, args.upstream, args.deps, args.threads)

if __name__ == "__main__":
    main()
