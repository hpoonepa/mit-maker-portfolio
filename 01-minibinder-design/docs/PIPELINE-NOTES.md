# Pipeline decisions and source records

The README describes the DWV campaign at the level of the build process. This
page connects those descriptions to the archived work and distinguishes the
design rationale from results that have actually been measured.

## What each part contributed

| Part of the work | Purpose | Record to inspect |
|---|---|---|
| Target-context review | Compare an isolated target fragment with the surrounding viral structure before interpreting a proposed interface. | Lambert modeling report, “Structural Analysis and Epitope Selection”; [PRINCE](../prince/) contains the later evidence-review tool. |
| Candidate generation | Explore different possible structures and interfaces using existing design frameworks. | [Mosaic campaign script](../source-history/scripts/mosaic_5g51_design.py), [BindCraft notebook](../source-history/scripts/bindcraft_5g51_colab.ipynb), [BoltzProt notebook](../source-history/scripts/boltzprot_colab.ipynb), and [archived candidate table](../legacy/5g51_minibinder_scored.csv), which includes BoltzGen entries. |
| Independent structural assessment | Compare complex predictions and assess the binder by itself, rather than relying only on the generator's preferred result. | [Validation source](../source-history/validators/), [positive-design metrics](../results/5g51/design-provenance/r10_l79_s469532_mpnn9_metrics.json), and the modeling report's structural-filtering section. |
| Sequence assessment | Examine sequence composition and properties associated with solubility or aggregation alongside structural evidence. | [SolubleMPNN comparison](../results/5g51/5g51_soluble_mpnn.csv) and the modeling report's sequence-filtering section. These tables contain computational sequence assessments; expression is evaluated separately. |
| Experimental selection and testing | Select a limited set of distinct candidates, then compare their predictions with assay outcomes. | [Final order](../results/5g51/design-provenance/5G51_FINAL_20_MASTER.csv), [round-one results](../results/bli/round1-adaptyv-summary.csv), and [round-two results](../results/bli/round2-adaptyv-summary.csv). |
| Analysis after the assays | Investigate why the single positive design was not the highest by minimum ipSAE and identify questions for further testing. | [Consensus-ranking analysis](../source-history/scripts/consensus_rank.py). Its header dates the derivation to 21 September 2026 and explicitly uses the observed assay results. Prospective evaluation of its proposed rules remains pending. |

The source archive contains scripts and notebooks from different iterations.
Each iteration has its own inputs, dependencies and entry points.

## Tool names and chronology

The Lambert design page names Mosaic, BindCraft, and BoltzGen. The modeling
report names Mosaic, BindCraft, and BoltzProt. Harsha confirmed on 25 October
2026 that both BoltzGen and BoltzProt were used at different stages. The README
retains both names rather than treating them as interchangeable. Boltz-2 and
Protenix are identified separately as structural-evaluation tools.

PRINCE's later evidence review revisits the functional rationale for a proposed
target region. Consensus ranking was developed after the assays. The process
graphic summarizes these iterations and shows the two experimental outcomes.

## Reading the numbers

The Lambert report records a second-round pool of 103 computational candidate
entries. Twenty designs from that pool were submitted for testing. Across both
rounds, the assay records contain 35 designs: one positive, 18 negative, and
16 unknown with no assay loading. A combined fit and its individual replicate
rows are not separate designs; filter the assay CSVs to `scope=overall`.

The report also describes an analysis of 5,721 labeled designs across 41 targets.
Minimum ipSAE performed better in that pooled comparison than several other
scores, but performance fell within individual targets. A naive ensemble of
38 metrics did not outperform the best individual score. The comparison examines pooled performance and performance within each target.

## Scientific background and the intended impact

DWV and Varroa are major contributors to colony losses. The project aimed to
develop a binder for eventual testing against infection. BLI measured binding
to the supplied target construct. Viral neutralization, binding-pose mapping
and colony-protection studies remain pending.

Published anti-DWV antibody work has shown reduced viral loads in bees. The motivation for exploring minibinders was
the prospect of practical production, storage, and delivery. In the Cao et al.
study, nine of thirteen characterized designs had reported melting temperatures
above 95°C; the other four did not. Thermal stability, acid resistance and stability in the bee digestive
environment remain unmeasured for this DWV binder.

| Source | What it supports |
|---|---|
| [MacMillan et al., 2024](https://journals.asm.org/doi/10.1128/msphere.00497-24) | DWV's contribution to colony loss and reduced DWV loads after antibody treatment in the study. |
| [Škubník et al., 2017](https://pmc.ncbi.nlm.nih.gov/articles/PMC5373406/) | The exposed VP3 P-domain and structural motivation for investigating it. |
| [Cao et al., 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9117152/) | De novo minibinder design and measured thermostability of those published designs. |
| [USDA ARS: honeybee health](https://www.ars.usda.gov/oc/br/ccd/index/) | Varroa, transmitted viruses, and the multiple contributors to colony losses. |

The local Lambert sources used for the rewrite are identified and hashed in
[the source record](../assets/story-sources.json). The README and process graphic
were prepared retrospectively for the portfolio. Original
experimental figures remain unchanged.
