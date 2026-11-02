# MarS-FM equilibrium-suite validation protocol

Status: frozen validation-stage protocol; no final-model or state-of-the-art
claim.

Frozen on 2026-07-31 after anchor08 passed the designated one-protein pilot,
but before generating source or anchor08 equilibrium outputs for the other
seven proteins.

## Population and generation

Use the first eight validation domains in the frozen 128x32 manifest whose
sequence length is at most the pinned model crop of 256 residues:
`1e7uA04`, `1rquA01`, `1q16B03`, `1d1rA00`, `2k4qA00`, `2f2cA02`,
`5k2mA01`, and `2dp9A01`.

For both pinned source MarS-FM and the seed-1 anchor08 candidate, generate the
official breadth-first tree with 200 children per call, 500 retained samples,
chunk size 100, 50 ODE steps, and seed `20260731`. Score against all five
450 K replicas with the existing all-C-alpha aligned equilibrium metrics.

## Protein-level retention gate

For each metric, define degradation in its unfavorable direction and use
proteins as the paired bootstrap unit with 100,000 resamples and seed
`20260801`. A metric passes only if:

1. the upper endpoint of its 95% bootstrap interval for mean degradation is
   no greater than the frozen per-protein pilot limit;
2. at least 75% of proteins individually remain within that limit; and
3. no protein degrades by more than twice that limit.

All seven metrics and their limits are inherited unchanged from
`MARS_FM_HYBRID_V1_PROTOCOL.md`. Every metric must pass. This is an internal
retention gate, not an equivalence test or evidence of field leadership.

Standard mdCATH test records remain unopened.
