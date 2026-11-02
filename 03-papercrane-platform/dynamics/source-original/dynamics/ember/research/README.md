# Source audit, 28 September 2026

These small public source/metadata snapshots and parser fixtures were acquired
through read-only downloads.
`sources.json` records repository commit IDs and file SHA-256 digests. Upstream
license files accompany code/fixtures. Checkpoint and dataset terms apply separately from code licenses; review
release-specific terms before the intended experiment or release.

## Verified changes from the older plan

- BioEmu's primary publication is in **Science (2025)**,
  DOI [10.1126/science.adv9817](https://doi.org/10.1126/science.adv9817).
  The old May document's Nature Methods attribution is incorrect.
- In the pinned BioEmu source, sidechain reconstruction saves all frames in XTC
  and saves only `[0]` in the PDB. The default output directory is `.`. The new
  command plan sets `--outpath` and preserves both files. A PDB-only split loses
  the ensemble. [Pinned implementation](https://github.com/microsoft/bioemu/blob/8babb71563e97dc1feb9e3e2fbc00a1224b6a3a7/src/bioemu/sidechain_relax.py).
- The real fpocket fixture uses `pocket1_atm.pdb` for Pocket 1, `Volume` in the
  descriptor file, and a distinct vertex PQR file. Its alpha-sphere count is not
  the number of pocket residues. [Pinned source](https://github.com/Discngine/fpocket/blob/4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066/src/writepocket.c).
- CryptoBench's original `Protein.py` computes trapezoidal area under the
  precision–recall curve. Ember's macro residue **average precision** is a
  different metric; these numbers must not be presented as interchangeable.
  [Author implementation](https://github.com/skrhakv/CryptoBench/blob/9a3432f479325ca3c9fdc3b8612715ab5b6edecc/src/I-final/Protein.py).

## Release inventory actually obtained

`cryptobench-release-inventory.json` lists the original OSF files, sizes, download
links and provider hashes. `cryptobench-metadata/receipts.json` verifies the files
downloaded here against OSF SHA-256 values.

| Original split | Apo structure IDs | Pair records in downloaded training annotations |
| --- | ---: | ---: |
| train-0 | 219 | 1,233 |
| train-1 | 222 | 1,327 |
| train-2 | 222 | 1,112 |
| train-3 | 222 | 721 |
| test | 222 | Not read/downloaded |
| Total | 1,107 | Training pair total: 4,393 |

The official PDB ID sets are disjoint; homology grouping remains pending. The
4,393 pair records and 1,107 structure IDs contain correlated pairs, chains and
ligand observations. Establish independent protein groups and the
monomer/length/chemistry-restricted cohort before analysis. Test annotations
remain outside the working files.

The original CIF archive is **1,145,203,712 bytes**. It was not downloaded.
`structure-fixtures/` instead contains three current RCSB structures selected by
hash of training PDB ID, with acquisition receipts. These fixtures check parser behavior; the benchmark release coordinates require
separate acquisition and identity verification:

| PDB / author chain | Canonical entity length | Observed residues |
| --- | ---: | ---: |
| 7R00 / AAA | 130 | 130 |
| 8JIS / R | 394 | 386 |
| 4OS8 / B | 190 | 162 |

8JIS exceeds the provisional length ceiling and is excluded from the eligible
cohort. These checks cover parsing; predictive evaluation remains pending.

`structure-fixtures/annotation-mapping-audit.json` also checks the exact original
training-annotation joins on these fixtures. All three mapped: 6/25/18 positive
residues and 1/1/2 custom reference sites respectively. The joins check annotation mapping. Biological eligibility and archived-coordinate
identity require separate audits.

`cryptobank-archive.json` contains accessible archive metadata and provider checksums.
The main dataset ZIP is 152,162,304 bytes. It was not downloaded or unpickled.
Confirm the experimental-apo slice, labels and cross-source overlap before using
CryptoBank as external evidence.

## Competitive implications

[Lacuna](https://github.com/mooreneural/lacuna) already offers an ensemble/detector/
ranker pipeline. [Seq2Pocket](https://github.com/skrhakv/seq2pocket) already converts
residue predictions into spatial pocket proposals. Ember’s prospective contribution is a reproducible improvement in
shortlist quality per dollar under a declared protocol, measured against these
existing methods. Their published numbers use different cohorts, metrics and candidate budgets;
Ember’s comparison requires measurements under the declared shared protocol.

The pinned Lacuna ranking/usage/benchmark documentation, CLI, report writer and
NMA source were inspected as well. The default CPU NMA/alpha/learned configuration
is a required inexpensive comparator. Explicitly select the backend: `auto`
depends on installed packages. Its report counts the apo input as one conformer;
the pocket count describes the emitted list. A saved six-pocket report is now a
parser fixture. Its benchmarks disclose repeated public-test measurement during
tool development, which must remain in the model-exposure inventory. Its PLM
ranking analysis motivates a mean-R0-logit control before crediting geometric
descriptors with a gain. See the pinned `docs/RANKING.md`, `docs/USAGE.md` and
`docs/BENCHMARKS.md` entries in `sources.json`; no Lacuna code was executed.

[PocketMiner](https://www.nature.com/articles/s41467-023-36699-3) motivates learning
structural signals associated with cryptic sites. Its simulation-derived labels
address cryptic-site annotations. BioEmu conformations are unordered samples;
the first Ember task is annotation recovery. Kinetics modeling requires
time-indexed data.

The current source snapshots support interface design. The next compute-authorized stage will test runtime compatibility,
actual model weights, all-atom reconstruction quality and comparable scientific
performance.
