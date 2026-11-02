# Data licences and attribution

This repository is MIT-licensed code. The **data** it describes is not ours, and
this file records exactly whose it is, under what terms, and what we deliberately
do not touch.

Nothing in this file is legal advice. It records what we checked and when
(2026-10-05) so that the next person can re-check rather than re-guess.

## What ships in git

- The pinned SAbDab summary and its source receipt in `benchmark/snapshot/`.
- The connected manifest in `data/eval/prince_connected.manifest.csv`.
- PRINCE model weights, a frozen ESM projection, and ordered feature metadata.
- Derived evaluation records and a small prepared-feature inference example.
- Two original DWV regression fixtures: the design table and reviewed evidence table.

No full coordinate archive, feature cache, upstream embedding weights, or comparator
weights are committed. Runtime downloads and generated research outputs are ignored
by git. See `ARTIFACTS.sha256` for the redistributed data-file checksums.

The snapshot is pinned because rebuilding against a changing upstream database is
not an identical experiment. The original snapshot receipt records its source,
fetch metadata, byte count, and digest.

## Sources used

### SAbDab2 — primary source (chain roles)

- **Snapshot terms:** the exact redistribution grant for the pinned database
  summary was not independently verified in the 1 November 2026 portfolio
  review. The cited article is CC-BY-4.0, but its article license alone does
  not establish a license for every database export. Preserve the source
  receipt and attribution; confirm the applicable snapshot terms with the
  provider before reuse beyond this documented research record.
- **Scientific citation:**

  > Schneider C, Raybould MIJ, Deane CM. SAbDab in the age of biotherapeutics:
  > updates including SAbDab-nano, the nanobody structure tracker.
  > *Nucleic Acids Research* 2022;50(D1):D1368–D1372.
  > doi:[10.1093/nar/gkab1050](https://doi.org/10.1093/nar/gkab1050)

- **Endpoint used:** `GET https://sabdab.opig.stats.ox.ac.uk/api/download/all-summary`
- **Why it is the primary source:** it is the only route that states *chain
  roles* — which chain is heavy, which is light, which is antigen. No RCSB
  query route provides that, and without it an epitope cannot be derived,
  because you do not know which atoms are the antibody.
- **Its chain identifiers are not all in one namespace, and the `antigen_chain`
  column is the mixed one.** `Hchain`/`Lchain` are author chain ids (possibly
  carrying an scFv domain index). `antigen_chain` holds author ids, but also
  `label_asym_id`s of ligand entities (1BJ1 `A` is a sulfate, 13DS `G|I|M` are
  glycerols), `label_asym_id`s of polypeptide chains (12UT `AB` is author chain
  `0`), and ids that name no chain in the current deposition at all.

  Resolution therefore happens against the coordinates in every namespace, the
  namespace that matched is recorded in the manifest's `chain_resolution`
  column, and an identifier that cannot be placed **drops the instance** rather
  than being replaced by some other chain that happens to be present — see
  `benchmark/epitope.resolve_antigen_chains`.

  Measured over the 16,897 antigen identifiers of the 9,081 protein-antigen
  instances whose coordinates the capped build fetched (70.4% of the 12,892
  instances in the table; the remainder are complexes the per-cluster cap
  discarded before download, so they are not part of the benchmark-eligible
  population and their coordinates were never retrieved):

  | namespace that answered | share | benchmark effect |
  |---|---|---|
  | `auth_asym_id` | 81.5% | used |
  | ligand/water `label_asym_id` | 12.1% | accounted for, excluded |
  | nothing, in any namespace | 3.2% | instance dropped |
  | `label_asym_id` of an antibody chain | 2.0% | refused |
  | `label_asym_id` of a polypeptide | 1.2% | used, after mapping to its author chain |
  | ambiguous case fold | 0.05% | instance dropped |

  Per instance: 3.8% are dropped for an unplaceable identifier and 1.0% get an
  antigen chain an author-space-only resolver would have omitted.

### RCSB PDB — coordinates and sequence/UniProt cross-references

- **Licence:** CC0-1.0 (public domain dedication). Attribution is encouraged,
  not required; we give it anyway.
- **Endpoints used:**
  - `GET https://files.rcsb.org/download/{PDBID}.cif.gz` — note the path is
    case-sensitive and wants the **uppercase** 4-character id, and `HTTP HEAD`
    against this host is blocked, so existence must be probed with `GET`.
  - `POST https://data.rcsb.org/graphql` — per-entity canonical sequences and
    UniProt accessions, used for redundancy clustering.
- **Cite:** Burley SK et al. RCSB Protein Data Bank. *Nucleic Acids Research*
  2023;51(D1):D488–D508. doi:10.1093/nar/gkac1077

### AsEP — cross-check and published splits

- **Licence:** CC-BY-4.0.
- **Archive:** Zenodo doi:[10.5281/zenodo.11495514](https://doi.org/10.5281/zenodo.11495514)
  — 1,723 complexes, 641 antigens, 973 epitope groups.
- **How it is used:** as an independent cross-check on our derived epitopes, and
  as a *secondary* sensitivity analysis via its published epitope-group split,
  joined on PDB id. We do **not** re-run MMseqs2 to reproduce that split, since
  that would add an alignment binary for a number the authors already provide.
- **Not vendored.** The archive is downloaded on demand, never committed.

### EBI PDBe — per-residue SIFTS mappings

- `GET https://www.ebi.ac.uk/pdbe/entry-files/download/{pdbid}_updated.cif` —
  note **lowercase** id here, unlike files.rcsb.org.
- [EMBL-EBI terms](https://www.ebi.ac.uk/about/terms-of-use/) preserve
  restrictions imposed by the underlying data owner and expect attribution.
  PDB archive coordinates are CC0 under the wwPDB policy; do not extend that
  grant to every EBI resource, mapping or external annotation.

## Comparison baselines — never vendored

An actual BepiPred-3.0 comparison has now run on the repaired test subset;
other listed predictors remain potential baselines, not measured results.
Keep third-party code/models under their own terms rather than presenting them
as MIT-licensed parts of this package. Non-commercial academic comparison can
be permitted even when redistribution or commercial deployment is not.

- **DiscoTope-3.0** — the [official repository](https://github.com/Magnushhoie/DiscoTope-3.0)
  carries [CC BY-NC-4.0](https://github.com/Magnushhoie/DiscoTope-3.0/blob/master/LICENSE).
  The specific dataset redistribution grant has not been established here;
  no DiscoTope dataset or model is included in this release.
- **SEMA** — the historical source review recorded an MIT file crediting
  AYLIEN (2016) and a CC BY-NC paper. That is insufficient evidence here to
  establish the rights for each dataset or model; none is redistributed.
  Its 8 Å / 16 Å-mask epitope convention also differs from the 4.5 Å
  minimum-heavy-atom-distance convention used here, so comparison requires
  reconciling the label definitions.

Historical prerequisite check (2026-10-09): the inspected
[DiscoTope fork](https://github.com/Youssef-Bakr/discotope3_web) specified
Python 3.9, PyTorch 1.11 and PyG/scatter dependencies tested on Ubuntu, plus
`models.zip` and ESM-IF1. This records that environment review, not the current
requirements of the official upstream repository. These dependencies/models
are not installed in the local PRINCE environment.
[BepiPred-3.0](https://github.com/UberClifford/BepiPred-3.0) supports CPU inference
and academic non-commercial use. Its pinned official classifier ensemble and
ESM-2 runtime were executed locally on 66 unique observed antigen sequences.
Predictions map to all 110 repaired test interfaces and 28,845 explicit residue
labels. Receipts, source revision and hashes are in
`evaluation/residue-baseline/`; upstream models remain outside the repository.
Its training-set overlap is unknown, so the comparison is retrospective, not
an untouched external test. No published score was borrowed from another dataset.

## Sources deliberately not used

Dockground, BioLiP2, and DIPS-Plus were considered during the original source
review but are not used or distributed by this release. Their datasets and
models are not bundled, and they do not supply the benchmark labels. The code
license in this repository does not grant rights to those separate resources.

## Derived labels

The epitope residue assignments in the manifest are **derived by this
repository's code** from CC0 RCSB coordinates, using chain roles from SAbDab. The code is MIT,
but that code license does not replace the underlying data terms. Preserve
the SAbDab scientific citation and snapshot receipt; the exact snapshot
redistribution grant remains unverified as described above.

The derivation is defined in `benchmark/epitope.py`: 4.5 Å minimum heavy-atom
(non-hydrogen) distance on the deposited asymmetric unit, after removing
hydrogens, alternate conformations and zero-occupancy atoms, with the antibody
atom set restricted to amino acids — the AsEP/PECAN convention. 4.0 Å is
reported as a sensitivity analysis.

## Embedding and measured-minibinder sources

The site ranker uses features from Meta ESM-2 (`facebook/esm2_t30_150M_UR50D`), with the model revision and projection receipt recorded in `evaluation/features/esm_receipt.json`. The upstream ESM model is separately distributed under its own MIT terms; its weights are not included here.

The separate measured-minibinder transfer study uses the [Anthropic `claude-protein-binder-design` dataset](https://huggingface.co/datasets/Anthropic/claude-protein-binder-design), whose official dataset card states CC-BY-4.0; the source URL and attribution are also retained in the research programs. This is a data-source attribution, and does not describe the PRINCE classifier's architecture. Those external dataset tables are not bundled.
