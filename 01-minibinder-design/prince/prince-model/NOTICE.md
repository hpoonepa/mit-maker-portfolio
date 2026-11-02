# Attribution

PRINCE is distributed under the MIT license; see [LICENSE](LICENSE). Data sources
and derived labels are described in [DATA_LICENSES.md](DATA_LICENSES.md).

## Software

| Dependency | Purpose | License |
|---|---|---|
| gemmi | Coordinates, assemblies, numbering, and structural parsing | MPL-2.0 |
| freesasa | Solvent-accessible surface area | MIT |
| typer | Command-line interface | MIT |
| PyYAML | Evidence and metadata input | MIT |
| numpy | Arrays and optional ranker inference | BSD-3-Clause |
| scipy | Benchmark geometry and statistics | BSD-3-Clause |
| xgboost | Saved patch classifier and research fitting | Apache-2.0 |
| scikit-learn | Grouped model selection and PCA | BSD-3-Clause |
| pandas | Research tables | BSD-3-Clause |
| pyarrow | Research Parquet files | Apache-2.0 |
| requests | Research data retrieval | Apache-2.0 |
| biopython | Research sequence operations | Biopython License Agreement |
| sbol3 | Optional SBOL3 constructs and annotations | MIT |
| pytest | Tests | MIT |
| jsonschema | Run-record validation in tests | MIT |
| tomli | TOML parsing for Python 3.10 tests | MIT |

ESM feature construction also requires separately installed PyTorch and
Transformers. Optional comparator programs load upstream BepiPred, PeSTo, or
ProteinMPNN models under their own licenses. Their code and weights are not
vendored into this release. Dependency version constraints are in `pyproject.toml`.

## Relative solvent accessibility

The primary maximum-accessibility denominator is measured from each input
structure using the same SASA settings as the numerator. A published table is
used only as a fallback for residue types the empirical procedure cannot price:

Tien MZ, Meyer AG, Sydykova DK, Spielman SJ, Wilke CO. Maximum allowed solvent
accessibilities of residues in proteins. PLoS ONE (2013), 8(11):e80635.
[doi:10.1371/journal.pone.0080635](https://doi.org/10.1371/journal.pone.0080635).

`PUBLISHED_MAX_SASA` uses the theoretical values from Table 1. The reference
method and calculation parameters are retained in run records.

## Reused statistics code

`benchmark/metrics.py` and `benchmark/bootstrap.py` were ported from the authors'
`binder-scorer` project (Paper Crane). The reused components include ranking
metrics, clustered BCa bootstrap intervals, and power calculations. Their module
docstrings preserve attribution. This is shared authorship of those components,
not an external model included in the PRINCE runtime.

## Interoperability

RFdiffusion, BindCraft, and BoltzGen are referenced as downstream design tools.
Their code and models are not included. Imported external epitope score files
retain the provenance of the predictor that generated them.
