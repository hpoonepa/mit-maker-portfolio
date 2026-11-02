# Citations and credits

This project combines campaign-specific scripts and analysis with existing scientific tools. It does not implement Mosaic, RFdiffusion, BindCraft, Boltz, Protenix, ProteinMPNN or ESM. Harsha's campaign/software contribution, Vedant's design contribution and Adaptyv's measurements are described in the [README](README.md). Local source headers, PRINCE's licenses/notices and saved artifact receipts remain part of the attribution record.

## Design and structure prediction

| Tool | Role here | Primary source and terms |
|---|---|---|
| Mosaic / Escalante Bio | Composite-objective optimization, scientific-model integration and ProteinMPNN interfaces imported by the campaign scripts | [Repository](https://github.com/escalante-bio/mosaic), including its `CITATION.cff` and MIT license. Model and dependency terms remain separate. |
| RFdiffusion / University of Washington Institute for Protein Design | Earlier structure-generation experiments | [Official source](https://github.com/RosettaCommons/RFdiffusion) and [BSD license](https://github.com/RosettaCommons/RFdiffusion/blob/main/LICENSE), which covers the source and referenced weights. Preserve the University of Washington and developer credits. |
| BindCraft / Martin Pacesa and collaborators | Binder generation, including the positive candidate's recorded lineage | [Official source](https://github.com/martinpacesa/BindCraft); [repository-linked preprint](https://www.biorxiv.org/content/10.1101/2024.09.30.615802). MIT code; PyRosetta has its own licensing conditions. |
| ProteinMPNN / Justas Dauparas and collaborators | Inverse folding and comparison of soluble versus standard sequence models | [Official source](https://github.com/dauparas/ProteinMPNN); [repository-linked paper](https://www.biorxiv.org/content/10.1101/2022.06.03.494563v1). MIT repository; soluble weights are explicitly identified there. |
| Boltz-2 | Independent complex prediction | [Official source](https://github.com/jwohlwend/boltz); [repository-linked paper](https://doi.org/10.1101/2025.06.14.659707). Official README states MIT code and model. |
| BoltzGen | A separate generative design workflow | [Official source](https://github.com/HannesStark/boltzgen), MIT. The campaign containers also record an Escalante Bio fork and exact revision. |
| BoltzProt / Boltz API | Hosted design client in `boltzprot_colab.ipynb`, which imports `boltz_api.Boltz` and saves job IDs | [Current official service documentation](https://docs.boltz.com/). Historical service naming does not make the hosted model or service MIT-licensed; use the applicable service terms. |
| Protenix / ByteDance | Independent structural evaluation through Mosaic; scripts refer to `ProtenixV2` | [Official source and technical-report links](https://github.com/bytedance/Protenix). Code is Apache-2.0. The official April 8, 2026 notice states that **Protenix-v2 weights are proprietary and cannot be redistributed without prior written consent**. They are not bundled here. |
| Chai-1 / Chai Discovery | Independent structural validation in earlier scripts and consensus scoring | [Official source and technical report](https://github.com/chaidiscovery/chai-lab). Official README states Apache-2.0 for code and weights. |
| ESM-2 / original ESMFold / Meta | PRINCE embedding-feature provenance and the `esmfold_v1` scoring wrapper | [Official ESM source and citations](https://github.com/facebookresearch/esm), MIT source. ESM Atlas data have separate terms. |
| ESMFold2 / Biohub and the Escalante Bio JAX port | Later model/fork integrations pinned in recorded container builds | [Biohub ESM](https://github.com/Biohub/esm) and [esmjfold2](https://github.com/escalante-bio/esmjfold2). The JAX port credits Apache-2.0 Biohub Transformers architecture code and an MIT Biohub structure-output writer. Keep its third-party notices and model-specific terms; it is not interchangeable with Meta's original ESMFold. |
| biomodals / Brian Naughton | Upstream Modal examples used in the earlier working environment | [Repository](https://github.com/hgbrian/biomodals), MIT, copyright Brian Naughton. This is an upstream tool collection, not applicant-developed scientific models. |

The stored containers and notebooks include these historical Git pins: Mosaic `70fec525423f5f87156a1a957b4a4048f9f8e676`, Escalante Boltz `1acc397b6e81f30dc07a80d17a26c38f9c6f6942`, Escalante BoltzGen `c0bbc7ec0dad7f7bc11d28cd83297fb02ddb757a`, Biohub ESM `26b0bc2b771e3e419ea74f445a5f35cc094a1509`, and esmjfold2 `40a33070c4db646152dc374c650f0dedf3c506a6`. Different campaign iterations use different revisions, including the older Mosaic `bca3152` noted in the V5 driver. These pins document the environments used across campaign iterations.

## Objective and metric references

- **ipSAE:** [DunbrackLab/IPSAE](https://github.com/DunbrackLab/IPSAE), MIT. The package imports Mosaic's differentiable versions; the scores and thresholds come from retrospective campaign analysis.
- **LIS:** Kim et al., *Enhanced Protein-Protein Interaction Discovery via AlphaFold-Multimer* (2024), [preprint](https://www.biorxiv.org/content/10.1101/2024.02.19.580970v1) and [AFM-LIS source](https://github.com/flyark/AFM-LIS), MIT. The local `LIS` class uses a soft contact-probability-weighted PAE expression; numerical parity with the authors' LIS/LIA and later iLIS implementations remains untested.
- **actifpTM:** Varga, Ovchinnikov and Schueler-Furman, *actifpTM: a refined confidence metric of AlphaFold2 predictions involving flexible regions*, Bioinformatics 41(3), btaf107 (2025), [article](https://pmc.ncbi.nlm.nih.gov/articles/PMC11925850/), [DOI](https://doi.org/10.1093/bioinformatics/btaf107). The local JAX objective adapts contact weighting; numerical parity with the published ColabFold implementation has not been established here.
- **pTMEnergy / BindEnergyCraft:** Nori, Parsan, Uhler and Jin, *BindEnergyCraft: Casting Protein Structure Predictors as Energy-Based Models for Binder Design* (2025), [arXiv:2505.21241](https://arxiv.org/abs/2505.21241). The local module re-exports Mosaic's `pTMEnergy` objective.
- **CONFIDE / CODE:** Gao et al., *CONFIDE: Hallucination Assessment for Reliable Biomolecular Structure Prediction and Design* (2025), [arXiv:2512.02033](https://arxiv.org/abs/2512.02033). `confide_score` in this source is an unimplemented local placeholder. Implementation and validation of the local sketch remain pending.
- **Relative SASA:** Tien et al., *Maximum allowed solvent accessibilities of residues in proteins*, PLOS ONE 8(11):e80635 (2013), [DOI](https://doi.org/10.1371/journal.pone.0080635). PRINCE preserves its table/method attribution in [NOTICE.md](prince/prince-model/NOTICE.md).

The campaign's retrospective consensus rules use its own observed assay outcomes. The rules were derived from one positive and statistically nonsignificant expression comparisons; prospective evaluation remains pending.

## Structures, data and biological context

| Source | Use and attribution |
|---|---|
| PDB [5G51](https://www.rcsb.org/structure/5G51), [5MV5](https://www.rcsb.org/structure/5MV5), [6F5J](https://www.rcsb.org/structure/6F5J) | DWV VP3/P-domain and virion structural context. The official 6F5J entry title mentions a GFP gene; that is the deposited structure's title, not a submitted GFP-design project. Cite each entry and its associated structural publication. |
| Škubník et al., *Structure of deformed wing virus, a major honey bee pathogen*, PNAS (2017) | [Primary article](https://pmc.ncbi.nlm.nih.gov/articles/PMC5373406/), DOI 10.1073/pnas.1615695114. Structural context for target selection. Neutralization testing of our binder remains pending. |
| RCSB PDB / wwPDB | [Official policy](https://www.rcsb.org/pages/policies): PDB archive files are CC0; integrated third-party resources retain their own terms. |
| PDBe / EMBL-EBI | Coordinate retrieval and mappings. [Current terms](https://www.ebi.ac.uk/about/terms-of-use/) retain underlying data-owner restrictions and expect attribution; do not label every EBI resource CC-BY. |
| SAbDab / SAbDab2 | Chain roles, a pinned summary and PRINCE-derived epitope labels. Schneider, Raybould and Deane, *SAbDab in the age of biotherapeutics: updates including SAbDab-nano*, NAR 50(D1):D1368–D1372 (2022), [DOI](https://doi.org/10.1093/nar/gkab1050), [provider](https://sabdab.opig.stats.ox.ac.uk/). The article is CC-BY; the database snapshot's separate redistribution grant remains unverified. Preserve receipts and attribution and confirm the applicable terms before further reuse. |
| AsEP | Separately downloaded cross-check/split source, [Zenodo record](https://doi.org/10.5281/zenodo.11495514); not bundled. Its use and source terms are recorded in PRINCE's data-attribution document. |
| BepiPred-3.0 | Comparator run, [official repository](https://github.com/UberClifford/BepiPred-3.0). Upstream code and weights are not redistributed; comparison results and provenance are. Follow the upstream academic/non-commercial conditions. |
| Anthropic measured binder dataset | [Official dataset card](https://huggingface.co/datasets/Anthropic/claude-protein-binder-design), CC-BY-4.0. Used by a separate PRINCE transfer study; external tables are not bundled. This is data-source attribution. |
| Adaptyv | Original BLI exports and selected sensorgram fits in `results/bli/`, produced for the Lambert team. These are the experimental records supporting this portfolio's binding result, not an external model benchmark. |

The [pipeline notes](docs/PIPELINE-NOTES.md) also cite MacMillan et al. (2024), [DOI 10.1128/msphere.00497-24](https://journals.asm.org/doi/10.1128/msphere.00497-24), on anti-DWV antibodies; Cao et al. (2022), [primary article](https://pmc.ncbi.nlm.nih.gov/articles/PMC9117152/), for measured properties of other published minibinders; and [USDA ARS](https://www.ars.usda.gov/oc/br/ccd/index/) for the multiple contributors to honeybee losses. None establishes this binder's heat tolerance, antiviral activity or colony protection.

PRINCE's [DATA_LICENSES.md](prince/prince-model/DATA_LICENSES.md) preserves detailed snapshot receipts, label derivation and comparator qualifications. Its code license does not grant additional rights to source datasets, model weights, papers or other authors' media.

## Retained learning experiments and compute tooling

The separate EGFR pilot records [BindCraft2](https://github.com/PacesaLab/BindCraft2), Mosaic, [UniProt](https://www.uniprot.org/), [AlphaFold DB](https://alphafold.ebi.ac.uk/) and PDB [6ARU](https://www.rcsb.org/structure/6ARU) as sources. Its molecular-dynamics option uses [OpenMM](https://openmm.org/) with the named `amber14-all.xml` and `amber14/tip3pfb.xml` parameter sets. These are the archived pilot's dependencies; the pilot and simulations were not rerun during this review. Follow each upstream version's terms and force-field references when reproducing that separate experiment.

The numerical/campaign wrappers also use JAX, Equinox, numpy, scipy, gemmi, Biopython, Matplotlib and PyYAML as declared in `pyproject.toml`; compute setup uses Modal, SSH, Docker and the named cloud providers. They are third-party infrastructure and libraries, not scientific methods authored for this portfolio. The oral-delivery script is a model based on the cited MacMillan measurements and stated assumptions, not a measurement of delivery by this minibinder.

## PRINCE software, source history and interface assets

The Python and web releases credit **Lambert iGEM 2026** under their retained MIT licenses. Their source references are [prince-model](https://gitlab.igem.org/2026/software/lambert-ga/prince-model) at `9a3551b` and [prince-webapp](https://gitlab.igem.org/2026/software/lambert-ga/prince-webapp) at `58883bd`. Each release history includes seven inherited iGEM starter-template commits beginning at `d46994c` in 2022; these are template provenance, not years of PRINCE development. The precursor [hotspot-preflight](https://github.com/hpoonepa/hotspot-preflight) has a separate development history. Original hashes, dates and authorship/coauthor metadata are preserved privately without rewriting or inventing a timeline.

PRINCE's [model NOTICE](prince/prince-model/NOTICE.md) credits gemmi, FreeSASA, Typer, PyYAML, numpy/scipy, XGBoost, scikit-learn, pandas, PyArrow, requests, Biopython, SBOL3 and test tooling. It also identifies benchmark statistics shared with the authors' Paper Crane project. The [web NOTICE](prince/prince-webapp/NOTICE.md) credits Astro, React, Three.js, TypeScript and fonts; exact web dependencies are locked in `package-lock.json`.

The bundled Inter font is unchanged. Its full [SIL OFL 1.1 text](prince/prince-webapp/public/licenses/inter.txt) comes from the [official tagged v4.1 license](https://github.com/rsms/inter/blob/v4.1/LICENSE.txt); the pre-existing binary's release version is unknown. Instrument Sans and Instrument Serif retain their license texts under `public/licenses/`. Public structure-derived figures retain their coordinate/source receipts. The demo is explicitly an earlier interface recording.

Resource checks were performed on 1 November 2026 using official repositories, provider pages and primary papers. Some DOI/bioRxiv pages blocked direct retrieval; those paper links were confirmed from the official tool repository. Inaccessible or incomplete license terms remain unresolved.

Potential epitope baselines that were not executed or bundled include
[DiscoTope-3.0](https://github.com/Magnushhoie/DiscoTope-3.0)
([paper](https://doi.org/10.3389/fimmu.2024.1322712), repository CC BY-NC-4.0).
The older prerequisite note refers to an inspected fork; the upstream project
and its current installation requirements are distinct from that historical check.
