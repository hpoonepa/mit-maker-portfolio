# Evidence provenance

The assay exports, predicted structures and candidate tables are retained records. Computational confidence scores are not measurements of binding, expression or antiviral activity.

## Experimental records

`bli/round1-adaptyv-summary.csv` contains 15 designs: nine negative and six unresolved results with no assay loading. `bli/round2-adaptyv-summary.csv` contains 20 designs, including one positive, `l79_s469532_mpnn9`. Filter to `scope=overall` to count designs: replicate and combined-fit rows are not additional proteins.

For the positive design, the overall apparent affinity is 6.036332e-7 M (about 604 nM), with replicate values of about 546 and 666 nM. The separately submitted figures are `bli/sg_rep31_f3.png` and `bli/sg_rep32_f6.png`; `bli/round2-fits.csv` identifies the fits. Adaptyv performed the measurements. These establish binding to the tested target construct, not neutralization or a measured binding pose.

`bli/first-batch-scores.csv` is the separately supplied first-batch score table. Its role and source are documented with the [build notes](../docs/BUILD-NOTES.md); it is distinct from the assay exports.

## Computational and order provenance

`5g51/design-provenance/5G51_FINAL_20_MASTER.csv` records the final order and contributions. `r10_l79_s469532_mpnn9_metrics.json` records computational metrics for the positive candidate. Other `5g51/` tables and `../legacy/` files preserve earlier candidate pools and model outputs, not additional experimental confirmations.

Some older records retain superseded hotspots or an abandoned putative catalytic-triad rationale. Keeping those rows documents the campaign's decisions; it does not endorse them. The [pipeline notes](../docs/PIPELINE-NOTES.md) distinguish target-context review, selection, and later analyses.

The consensus ranker was derived on 21 September 2026 after joining observed assay outcomes. Its thresholds were chosen with one positive; the reported expression-oriented comparisons did not reach statistical significance. It is a hypothesis for subsequent evaluation, not a validated predictor or evidence that it selected the original positive design.

PRINCE's separate frozen evaluation retains its own source receipts and data attributions. Those antibody-epitope benchmarks do not establish minibinder affinity or experimental success.

## Sequence strings and automated scans

Several protein sequences contain uppercase substrings matching common credential-detector patterns. Review such matches in their sequence context rather than changing measured or designed sequences. Credentials are not required to read these records; account configuration belongs outside the source tree.
