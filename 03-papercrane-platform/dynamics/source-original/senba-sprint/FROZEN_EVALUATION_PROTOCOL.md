# Frozen-checkpoint evaluation v1

Astra reviewed and approved this limited experiment on 4 September 2026. This is
a new implementation of validation-only evaluation, not an exact reproduction of
the unavailable original evaluator. The original training protocol remains separate.

## Frozen workload

Pilot protein: `1e7uA04`.

Expansion panel, chosen before new model outputs: `1e7uA04`, `1rquA01`, `1q16B03`,
`1d1rA00`, `2k4qA00`, `2f2cA02`, `5k2mA01`, `2dp9A01`. These are the first eight
domains explicitly named in the published validation protocol. No substitutions.

Source weights SHA-256:
`f56794cc5d1a8e5263031944f932384dd785fe945553612fe76fe1e9191fa879`.
Candidate weights SHA-256:
`f02dcf6a97848c834e3c0be7d848c1068d1d0eb7976d8d6bcfbc98d4114e9c7c`.
Upstream model implementation commit:
`4fc17d86cd7e22dda6353f2f1f6bf4b40c9ce946`.
Public mdCATH revision: `5e3ed8aec62b689e01751db16275fdcdbc39e47f`.

For each domain: all five 450 K replicas, four starts per replica, lag exactly
50 saved frames within that replica. For N available frames choose
`floor(i * (N - 51) / 3)` for i = 0, 1, 2, 3. Reject duplicates or missing future
frames. This explicit start rule is newly specified; equivalence to the original
run's starts is not established.

Map the provider's protein atom topology to complete atom14 residues, retaining
all required heavy atoms, in angstrom units. Read only the selected input/target
frames. Keep float32 inputs (no recreation of upstream float16 preprocessing),
record all shifts and atom indices, and retain file hashes and frame metadata.

Primary workload K=4 independent draws, 10 ODE steps. Set generation seed to
20260904 + transition index (replica-major, start-minor); reset identically for
source and candidate. Verify matching pre/post RNG states. Same streams across
models are paired comparisons, not extra training replications. Disable TF32.

The actual torch/library versions, code file hashes, trajectory metadata and
model hashes are captured with every run before outputs are generated.

## Scoring

Align target and each generated sample to the start's C-alpha coordinates using
proper Kabsch rotations (no reflections). Never align predictions to the future
target. Preserve raw and aligned coordinates. The primary metric is protein-macro
centroid endpoint RMSD; compare source and coordinate persistence. Also report
explicit mean individual-draw RMSD, squared-error decomposition, ensemble variance,
pairwise spread and exploratory energy score with the unbiased off-diagonal
Euclidean pairwise term. Negative candidate-source score differences favor SENBA;
there is no intrinsically favorable sign for changes in spread.

Use paired protein bootstraps. There are at most eight protein-level units and
one evaluated training seed. Do not create a cross-seed result from different
inference draws. All panels have been used during earlier development; these are
conditional validation diagnostics, not untouched generalization evidence.

## Expansion and budget

Pilot success means correct identities, topology, complete finite results,
paired randomness, numerical scoring checks, and affordable execution. Whether
SENBA improves is not an expansion criterion. An implementation failure pauses
dependent jobs and remains logged; it does not justify replacing the protein.

Working account: Modal profile `senba-sprint`. Total planning ceiling $30, reserve
$10. One H100 pilot, maximum 900 seconds execution + 180 startup, zero automatic
retries, two CPU cores and 16 GiB memory, with $3 conservatively reserved. Rates
were checked at https://modal.com/pricing; startup, idle/build cost and unbilled
commitments count. A local ledger is not a provider billing hard cap.

After the pilot, independent domains may run concurrently within the ledger's
remaining capacity. User explicitly authorized parallel GPUs. Price those jobs
from measured pilot throughput and conservative timeouts before release.

If resources permit, sampling sensitivity may extend the fixed panel from K=4 to
K=16, preserving original draws and scoring fixed prefixes K=4,8,16. A new single
K=16 batch with altered RNG batching must not be passed off as preserving the
original K=4 draws. The sensitivity estimates are dependent, not replications.

## Claim boundary

An independent implementation re-evaluates a frozen public checkpoint on a
previously used validation panel and examines its endpoint and distribution-score
behavior. It does not prove source-distribution preservation, physical kinetics,
untouched test generalization, methodological necessity, or conference acceptance.
No new fitting, alpha search, other training seed, or sealed test access is included.

## Sampling extension execution amendment

Frozen on 4 September 2026 after K=4 results were available and before any new
sampling-extension outputs. The decision to extend this entire fixed panel if
affordable was specified above before the pilot. No protein, checkpoint, metric,
or start is selected based on K=4 gains. This is a dependent sensitivity check.

Retain each original K=4 ensemble exactly. For each of the same 160 transitions,
generate three additional blocks of four draws, using seeds
`20260904 + transition_index + block_index * 1000000`, with block indices 1, 2,
3. Reset each seed identically for source and candidate. Keep K=4 vectorized
batch shape, ten ODE steps, the same checkpoints, inputs, alignment, and Torch
environment. Merge only after matching provenance, raw targets and starting
coordinates. Score nested prefixes K=4, K=8 (original plus block 1), and K=16
(all four blocks) separately. The first K=4 prefix must exactly match the stored
original sample arrays. Preserve every block's RNG and source-file receipts.

Run eight independent H100 workers with at most 600 execution seconds and 180
startup seconds each, no automatic retries and $2 reserved per worker. The K=4
run's measured paired-inference totals were 102–164 seconds per protein; three
additional blocks are expected to fit this bound but failures remain reportable.
After confirming all original apps stopped with zero tasks, the provider's
reported K=4 charges were $1.23086024. A separate $2 commitment covers billing
lag/overhead, in addition to the unchanged $10 reserve. Thus reported charges +
late-charge allowance + eight new reservations + reserve = $29.23086024.
This is conservative local accounting, not a final invoice or a provider hard cap.
