# PRINCE Model

**Surface-site ranking and structural checks for protein binder projects.**

Choosing a binder's target residues is an upstream decision: missing coordinates, a buried surface, or a numbering mismatch can make a sensible-looking design specification unusable. PRINCE helps inspect that decision before binder generation.

This repository contains the Python analysis package, two frozen model artifacts, the site-ranking research code, and the evaluation records assembled by Lambert iGEM 2026. The companion **[prince-webapp](https://gitlab.igem.org/2026/software/lambert-ga/prince-webapp)** repository provides the browser interface.

[Quick start](#quick-start) · [Saved site ranker](#use-the-saved-site-ranker) · [Model card](MODEL_CARD.md) · [Reproduction guide](docs/reproducibility.md) · [CLI reference](docs/command-line-reference.md)

## Choose the right entry point

| Your task | Entry point | Model or method |
|---|---|---|
| Check a proposed hotspot list | `preflight check` | Structural validity checks |
| Analyze a PDB/mmCIF structure | `preflight analyze` | Four-feature residue scorer and connected surface patches |
| Run the browser workspace | `preflight serve` | The same lightweight analysis package |
| Score prepared patch features | `prince-rank` | Frozen 400-tree XGBoost site ranker |
| Study training and evaluation | `research/` and `evaluation/` | Grouped model selection, controls, and audits |

**The two models are different.** The web service uses the lightweight residue scorer. The stronger site ranker accepts prepared features through a separate command; it is not silently substituted into the web service.

## Quick start

Python **3.10 or later** is required. Use Python 3.11 for the CI environment. A CPU is sufficient for the installed analysis service and saved-model inference. Building ESM features for the research pipeline is a separate, heavier task.

Clone the repository and install the package:

```sh
git clone https://gitlab.igem.org/2026/software/lambert-ga/prince-model.git
cd prince-model
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install '.[dev,benchmark,sbol,ranker]'
```

On Windows, activate `.venv\Scripts\Activate.ps1`. FreeSASA may need native build tools when a wheel is unavailable; on Debian/Ubuntu, install `build-essential` and `python3-dev` first. Keep Python and its compiled dependencies on the same CPU architecture.

### Analyze a public structure

```sh
preflight analyze 1ubq --chain A --top 3 --json analysis.json
```

This retrieves public coordinates from PDBe, enumerates connected surface patches, ranks them with the residue baseline, and writes the proposals and checks to JSON. A first lookup needs internet access. For a local file:

```sh
preflight analyze target.cif --chain A --top 3 --json analysis.json
```

Use mmCIF when possible: it can retain biological assemblies, author numbering, sequence declarations, and unresolved-residue annotations that a PDB file may lack.

### Check known hotspots

```sh
preflight check 6f5j --hotspots C405,C408
```

This example returns **STOP**: those residues are declared but unmodelled in the deposited coordinates. The exit code is **2**, which is a completed structural finding rather than a software crash.

| Exit code for `preflight check` | Meaning |
|---|---|
| `0` | GO |
| `1` | GO_WITH_WARNINGS |
| `2` | STOP |
| `3` | Invalid input or execution error |

`preflight analyze` and `preflight propose` use 0 for completed execution and 3 for input/execution errors; inspect their result records for structural verdicts. `prince-rank` uses 0 for success and 2 for invalid input or an unavailable inference dependency.

### Run the web app worker

```sh
preflight serve --port 18766 \
  --allow-origin http://127.0.0.1:4330 \
  --allow-origin http://localhost:4330
```

The service binds to `127.0.0.1`. See [docs/api.md](docs/api.md) for requests and response fields. Start the companion frontend separately with `npm run dev`.

## Use the saved site ranker

The saved XGBoost classifier has **400 trees**, maximum depth **6**, and **660 ordered inputs**. It scores prepared surface patches and applies greedy diversity selection with Jaccard overlap suppression at **0.5**.

```sh
prince-rank --describe > feature-schema.json
prince-rank examples/patches.json --top 3 --output ranked.json
```

The bundled example is a small excerpt of real, already-computed patch features. Its source and expected scores are recorded in [examples/README.md](examples/README.md). It is an inference check, not a new performance experiment.

For your own data, use the exact feature order in [feature_schema.json](src/prince_ranker/data/feature_schema.json):

| Block | Residue features | Patch columns |
|---|---:|---:|
| Geometry and physicochemistry | 51 | 153 |
| Atom environment | 104 | 312 |
| ESM-2, projected with the frozen PCA | 64 | 192 |
| Residue count, area, radius of gyration | — | 3 |
| **Total** | **219** | **660** |

Within each block the order is all means, all maxima, then all population standard deviations. Blocks are concatenated as geometry, atom, ESM, then the three patch descriptors. The wrapper validates names, dimensions, finite numbers, residue lists, and the PCA identifier. It cannot establish that a caller actually used the stated feature-generation method.

**Do not fill missing feature blocks with zeros or refit the PCA and feed it to the existing trees.** The saved model depends on the supplied projection. Coordinate-to-feature construction is documented in [docs/reproducibility.md](docs/reproducibility.md); `prince-rank` itself does not accept a PDB file.

Python use:

```python
import json
from prince_ranker import rank_patches

with open("examples/patches.json") as handle:
    patches = json.load(handle)
result = rank_patches(patches, top=3)
for patch in result["ranked"]:
    print(patch["rank"], patch["residues"], patch["score"])
```

## What the evaluation supports

The site-ranking endpoint is **cluster-macro majority-hit at top 3**: an interface is a hit if any of its three selected patches contains more than 50% true epitope residues; interfaces are averaged within antigen clusters, then clusters are averaged equally.

| Held-out subset | Antigen clusters | PRINCE top-3 | Random control | Difference |
|---|---:|---:|---:|---:|
| Full test split | 251 | 0.508 | 0.233 | +0.276 |
| No training homolog at ≥50% identity | 121 | 0.452 | 0.232 | +0.220 |
| No training homolog at ≥30% identity | 93 | 0.458 | 0.238 | +0.220 |
| SAbDab2 40% identity clean subset | 80 | 0.439 | 0.261 | +0.177 |

For a concise result, report **approximately 0.44–0.46 top-3 majority-hit on 80–93 non-homologous antigen clusters, 0.18–0.22 above the matched random control**. The full split contains homologs across train and test. The clean subsets were analyzed after the test had been read; they are audits of that split, not new prospective validation.

The residue baseline used by the service has macro AUROC **0.648**, compared with **0.645** for exposure alone. That small difference does not establish a useful improvement. Its metrics and the site-ranking endpoint should not be interchanged.

Read the [model card](MODEL_CARD.md) for training counts, limitations, and source artifacts. The data support antibody-epitope localization, not minibinder designability, binding affinity, or experimental success.

## Reproduce and verify

```sh
python -m pytest
python scripts/verify_artifacts.py
python -m pip wheel . --no-deps --wheel-dir dist
```

Most tests are synthetic and run offline. Tests requiring public structures can skip if coordinates cannot be downloaded; a skipped test is not a passed structure check. The GitLab pipeline runs the tests, checks artifact hashes, and builds a wheel. Optional standards checks and environment details are documented in [CONTRIBUTING.md](CONTRIBUTING.md).

The full training pipeline is retained in `research/`, with generated data rooted at `PRINCE_DATA_DIR` (default: `work/`). The original feature caches are roughly **40 GB** and are not distributed here. Rebuilding the complete study requires coordinate downloads, embedding weights, compute time, and the input contracts in the reproduction guide. The frozen artifacts can be inspected and the bundled inference example can be run without rebuilding them.

## Repository map

```text
src/hotspot_preflight/   Structural checks, residue baseline, CLI, local API
src/prince_ranker/      Validated inference wrapper and frozen ranker artifacts
benchmark/             Manifest, label, split, and metric implementations
scripts/               Baseline fitting and evaluation commands
research/              Feature construction, grouped selection, sensitivity audits
evaluation/            Frozen results, controls, and provenance receipts
data/eval/             Connected manifest and baseline evaluation artifacts
examples/              Small prepared-feature inference example
tests/                 Structural, evidence, CLI, metadata, and ranker checks
docs/                  API, methods, reproducibility, and release notes
```

The installed distribution keeps the existing name **`hotspot-preflight`** for compatibility. The repository name is **`prince-model`**. The `preflight` command and `hotspot_preflight` imports remain stable.

## Limits that affect use

- Scores rank candidate sites; they are not calibrated binding probabilities.
- A patch can be mostly epitope while covering only a small part of that epitope. Majority-hit and epitope recovery answer different questions.
- Bound-complex conformations may differ from an unbound or experimental target.
- Exact-sequence/accession grouping does not establish homology independence.
- Evidence-assisted ranking requires reviewed, attributed evidence and has no measured predictive improvement in this release.
- The frozen ESM projection carries a provisional flag from the original experiment. Preserve its identifier when reproducing the saved model.
- Structural validity does not establish biological safety or suitability for a particular experiment.

## Contributing, license, and citation

See [CONTRIBUTING.md](CONTRIBUTING.md) for change and validation guidance, [LICENSE](LICENSE) for the MIT code license, [NOTICE.md](NOTICE.md) for software attribution, and [DATA_LICENSES.md](DATA_LICENSES.md) for data provenance. Third-party data and comparator models keep their own terms.

Cite **Lambert iGEM 2026, PRINCE Model / hotspot-preflight**, version 0.1.0, and the release or commit used. [CITATION.cff](CITATION.cff) and [codemeta.json](codemeta.json) provide machine-readable metadata and the source repository URL. No archival DOI is assigned to this source release.
