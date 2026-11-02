# Reproducing PRINCE

There are three different levels of reproduction. Choose the one you need before downloading large inputs.

## 1. Inspect the frozen results

The `evaluation/` directory contains the saved site-selection metrics, random controls, homology audits, label-sampling audit, and residue-baseline comparisons. `benchmark/snapshot/` contains the pinned SAbDab source table and its receipt. `data/eval/prince_connected.manifest.csv` contains the connected manifest.

```sh
python scripts/verify_artifacts.py
```

Historical receipts retain their original numerical results and recorded code hashes. Local workstation paths were normalized for redistribution. Those historical hashes are provenance, not hashes of the reorganized source. `ARTIFACTS.sha256` verifies the current distributed artifacts.

## 2. Repeat saved-model inference

Install `.[ranker]` and run the example in the README. `examples/expected.json` records expected scores from the original XGBoost classifier interface. The regression test compares the new inference wrapper with those values and checks overlap suppression separately.

The classifier uses the bundled PCA projection, identifier `57d5bd1fce5fedbc`. The projection JSON includes the training mean and components. It is not enough to load an arbitrary ESM embedding with the same dimension. The exact observed-residue order, feature definitions, and projection must agree.

This path does not retrain or re-evaluate the benchmark. It tests whether the saved weights produce the expected output on a small real input.

## 3. Rebuild features and retrain

The original classifier used Python 3.10.9, XGBoost 2.1.0, and scikit-learn 1.2.1. Use a separate Python 3.10/3.11 environment for historical research dependencies:

```sh
python3.10 -m venv .venv-research
source .venv-research/bin/activate
python -m pip install '.[research]'
export PRINCE_DATA_DIR="$PWD/work"
mkdir -p "$PRINCE_DATA_DIR"
```

The full cache is approximately 40 GB. Coordinates are downloaded into `.cache/benchmark/cif`; generated research data goes to `PRINCE_DATA_DIR`. No private workstation paths or symlinks are required.

Start with a small structural smoke run:

```sh
python research/build_cache_all.py --limit 2 --workers 1
```

Then build the complete cache and atom block:

```sh
python research/build_cache_all.py --workers 3
python research/build_atom_features.py \
  --cache-dir "$PRINCE_DATA_DIR/cache_all" \
  --out-dir "$PRINCE_DATA_DIR/atom_cache" --workers 3
```

Embedding construction is optional for geometry-only experiments but required by the saved winning configuration. `research/build_esm.py` uses PyTorch and Transformers, which are not installed by the lightweight runtime. Install those for your hardware and inspect `python research/build_esm.py --help` before a large run. It downloads the declared ESM-2 model and constructs a training-only PCA:

```sh
python research/build_esm.py --cache-dir cache_all --out-dir esm_cache
python research/sweep.py --phase pack --blocks geom atom esm
python research/sweep.py --phase cv --blocks geom atom esm --kinds patch_classifier
python research/sweep.py --phase lock --blocks geom atom esm
python research/sweep.py --phase test --blocks geom atom esm
```

This sequence runs a new experiment. A new PCA fit is paired with newly fitted trees; it must not replace the projection for the distributed frozen classifier. Rebuilding inputs from live upstream sources can change availability or coordinates. Compare input hashes, context counts, feature order, and label-identity assertions before comparing performance.

The `cv` command above restricts the study to classifier candidates on the selected feature blocks. It is a practical reproduction route, not a claim to rerun every exploratory model family or optional ProteinMPNN arm. The original search history is in the frozen receipts and `research/PROTOCOL.md`.

## Audit and comparator scripts

The homology audit requires the relevant alignment tools and split inputs. Minibinder-transfer scripts require the original external dataset tables. BepiPred and PeSTo adapters require separately installed upstream models under their own terms. They are not vendored, and those experiments are not part of `pip install .` or the default test suite.

Several historical audit commands also use complete cached context features and prediction tables that are not included in this small release. They fail when those inputs are absent; do not create empty files or synthetic substitutes to make them run. Their saved results remain available for inspection.

## What was verified for this repository split

See [release-verification.md](release-verification.md). Source reorganization, package behavior, artifact identity, inference parity, and web integration are separate checks from retraining. No fresh full training or prospective biological validation is claimed.

Two small regression fixtures omitted from the organized package were recovered from the original analysis source: the 26-row DWV design table and the reviewed DWV evidence table. Their contents are preserved for the existing regression tests.
