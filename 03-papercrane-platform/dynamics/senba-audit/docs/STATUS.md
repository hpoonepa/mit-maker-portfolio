# SENBA sprint status

## Completed locally

- One Astra science review; implementation handled by Sol and Terra subagents.
- Corrected experimental sequence, statistical interpretation and cost accounting.
- Runnable coordinate-analysis, public-mdCATH extraction, paired checkpoint inference,
  and bounded reporting tools, with local tests and synthetic end-to-end verification.
- Offline preflight/planning and atomic budget ledger configured for a $30 total
  ceiling. Provider-reported charges are $4.56762390: $1.23086024 for K=4 and
  $3.33676366 for the sampling augmentation. All 16 applications are stopped
  with zero active tasks. The ledger retains a $2 late-billing allowance and the
  untouched $10 reserve. It is an accounting guard, not a provider billing cap
  or final invoice.
- Modal browser authentication succeeded for workspace `hpoonepa-42439`, saved
  under the separate `senba-sprint` profile. Commands must select that profile
  explicitly; the user's default profile was not changed. The $30 planning ceiling
  follows the user's expected credits, not a verified remaining-balance figure.
- Downloaded `vkali08/senba` at `90cce9e822d511459a206ae3a06cbd8dbb243b09`.
- Verified the 136,711,098-byte checkpoint's SHA-256 against its published identity.
- Verified 21 of the release manifest's 22 listed files, including all receipts,
  all protocols, the inference script and the checkpoint. The README mismatches.
- Recomputed the full 28-protein summary arithmetic and performed a leave-one-out
  robustness check using the public per-protein receipts.
- Pinned and verified the public MarS-FM source checkout, source checkpoint, and
  eight public mdCATH domain files used by the new frozen evaluation.

## Completed frozen evaluation

The real `1e7uA04` pilot finished on Modal and produced all 20 planned paired
transitions. Its live application is
[ap-OFWoTF9AIsGeU8eNkGeTjM](https://modal.com/apps/hpoonepa-42439/main/ap-OFWoTF9AIsGeU8eNkGeTjM).
The seven remaining compact-panel jobs and all eight sampling-augmentation jobs
also finished. The final dataset contains 160 physical transitions and K=16
samples per model, or 5,120 generated structures across source and candidate.
Receipts show every application stopped with zero active tasks.

The frozen workload is eight previously used validation proteins, with five 450 K
replicas and four starts per replica: `8 * 20` physical transitions. Source and
candidate each have prefix-preserving K=4, K=8 and K=16 summaries with ten ODE
steps. Only the released seed-1 candidate (training seed `20260825`) is evaluated.
This is a new, independently implemented evaluator on reused validation data; its
frame rule, float32 extraction and alignment path have not been shown equivalent
to the unavailable original evaluator. It is therefore not an exact reproduction
or independent test result.

| Samples per model | Endpoint centroid RMSD, candidate − source (angstrom) | Protein-bootstrap 95% interval | Energy score, candidate − source (angstrom) | Protein-bootstrap 95% interval |
| ---: | ---: | ---: | ---: | ---: |
| K=4 | -0.02401 | [-0.02882, -0.01870] | -0.003278 | [-0.007674, 0.001153] |
| K=8 | -0.01887 | [-0.02257, -0.01545] | -0.006037 | [-0.008406, -0.003590] |
| K=16 | -0.01383 | [-0.02194, -0.007334] | -0.006422 | [-0.01166, -0.001599] |

At K=16, equal-protein source and candidate endpoint centroid RMSDs are
10.04243879 and 10.02861107 angstrom, respectively: a -0.01382772 angstrom
candidate-minus-source difference, about 0.138%, with endpoint improvement on
8/8 proteins. Energy score improves on 7/8 proteins, with equal-protein difference
-0.00642231 angstrom and conditional interval [-0.01166227, -0.00159859]. The
endpoint gain magnitude shrinks 42.4% from the K=4 value of 0.02400558 angstrom,
showing material finite-K sensitivity. Lower ensemble spread has no intrinsically
favorable interpretation and does not establish preserved biological diversity.

These are conditional endpoint results for one released training seed on the same
reused eight-protein validation panel, not evidence of broad-dynamics improvement.
See [RESULTS_SUMMARY.md](RESULTS_SUMMARY.md) and the complete
[K=4](../reports/sampling-k4-v1/results.md),
[K=8](../reports/sampling-k8-v1/results.md) and
[K=16](../reports/sampling-k16-v1/results.md) reports.

## What the receipt audit established

| Check | Result |
| --- | --- |
| Six reported macro improvements | All match to 1e-12 |
| Centroid RMSD gain | 0.0325922111581212 angstrom; 27/28 proteins positive |
| Published single-sample field | Mean gain 0.06889705353038263 angstrom; 28/28 positive |
| Centroid gain vs persistence | 0.4364052826817221 angstrom; 22/28 positive |
| Source-comparison 95% bootstrap interval | Exactly matches [0.02525014950148637, 0.040114625364512255] |
| Leave-one-protein-out centroid mean gain | All positive; range [0.030778547791481852, 0.0339790180695553] angstrom |
| Persistence interval | Does not exactly reproduce with the tested bootstrap implementation |

The published persistence interval is [0.20302960346670967, 0.6806461308413764].
Using NumPy default_rng, seed 20260825, 100,000 shared protein-index resamples and
linear quantiles gives [0.20500703739876155, 0.680112003477885]. This does not alter
the positive sign, but the original evaluator is needed to resolve RNG ordering
or another implementation difference. A second sequential RNG block also did not
reproduce it. We did not search seeds to force agreement.

These are arithmetic checks of released summaries, **not raw-coordinate replication**.
The `single_sample` field's precise definition (first draw or mean over K) needs the
original evaluator. The receipt alone cannot yield an energy score or prove that
diversity is preserved. Leave-one-out robustness does not remove validation reuse.

## Release/documentation discrepancies

1. The manifest repository and a README download command reference
   `pikachuandme1/senba`, while the supplied and pinned repository is `vkali08/senba`.
   Downloads use the user-supplied account only.
2. README observed hash:
   `ec11820f293b150695d011d8e670a58a07c706b45f7cb073a4987899474dd2ed`, 9,339 bytes.
   Manifest expectation:
   `12c7c1f8e7088a4c28d99a76e5fb1d68880cc9206f56976880a3725d402f073b`, 11,374 bytes.
   The mismatch is isolated to this listed file; weights and receipts match.
3. The initial epoch-sweep protocol lists 10-epoch alpha values 0.02, 0.03, 0.04
   and 0.06; the selected alpha is 0.0735. Document the subsequent refinement or
   amendment and its timing before claiming that the exact selected coefficient
   was in the original frozen grid. The release reports an anchor search, but this
   protocol alone does not pre-register 0.0735.

No remote release files have been modified. Both upstream expectations and observed
hashes are preserved in `artifacts/hf-release/release-snapshot.json`.

## Final scope boundary

G0 is complete as a public-artifact audit: public artifact integrity, public
source/data identities and summary arithmetic are checked. Exact raw-coordinate
reproduction against the original evaluator was not possible with the published
materials. G1 is complete only as the limited real paired eight-protein evaluation
described above. The G3 sampling-size sensitivity component is also complete.

The public release omits the adaptation/evaluation code, exact train/validation
CSV contents, raw input/output arrays and additional seed checkpoints. The user has
confirmed these missing assets are not available. Consequently, original G2
additional-training-seed experiments, the original G3 training comparator and G4
frontier experiments are **not done**. The receipt's references to
`baselines/mars_fm/adaptation_data/128x32/train.csv` and `val.csv` identify files
that would have been required; checksums alone cannot reconstruct them.

No further jobs are queued. All applications are stopped, the reported billing is
$4.56762390, the $2 late-billing allowance remains held, and the $10 reserve remains
untouched. The completed G3 sampling component must not be relabeled as the missing
training-comparator experiment.

The existing PDF has not been rewritten; `SCIENTIFIC_REVIEW.md` and this status
supersede its overconfident scientific gates and incorrect cost-range sum.
