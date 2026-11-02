# MarS-FM Anchor08 complete eligible validation protocol

Status: frozen validation-stage protocol; no test, final-model, commercial,
state-of-the-art, or field-changing claim.

Frozen on 2026-08-02 after the seed-1 Anchor08 candidate passed the previously
frozen eight-protein transition and equilibrium-retention suites, but before
generating or inspecting exact-lag outputs for the remaining twenty eligible
validation proteins.

## Scientific question

Does the small exact-lag transition gain of the frozen seed-1 Anchor08
checkpoint survive the complete sequence-length-eligible validation population
without changing the checkpoint, inference settings, metrics, or population?

This is a candidate-qualification experiment. A pass does not establish
physical kinetics, broad sequence generalization, field leadership, or test
performance.

## Immutable identities

- Standard mdCATH manifest:
  `sha256:53e81a90c0dcf3e00a814744f62d25db52f5aa8790475294dac451d36d728b8b`.
- Development subset manifest:
  `sha256:163ab0043d86b5a2731e1b1a233af27fb069049897d657fd5c39bd54b1343b3f`.
- Source MarS-FM checkpoint:
  `sha256:f56794cc5d1a8e5263031944f932384dd785fe945553612fe76fe1e9191fa879`.
- Candidate run:
  `mars-fm-mdcath-anchor08-exactlag-128x32-20260801-s1-v1`.
- Candidate checkpoint:
  `sha256:802042f2d5c1aa8adf07a9a935063ed970aa38fdfba1993b236cb0364c9a0fae`.
- MarS-FM source revision:
  `4fc17d86cd7e22dda6353f2f1f6bf4b40c9ce946`.
- Standard test records opened: zero.

## Complete eligible population

Use every validation record in frozen manifest order whose sequence length is
at most the pinned MarS-FM crop of 256 residues. No eligible protein may be
removed after evaluation starts:

1. `1e7uA04` (158)
2. `1rquA01` (52)
3. `1q16B03` (77)
4. `1d1rA00` (83)
5. `2k4qA00` (156)
6. `2f2cA02` (106)
7. `5k2mA01` (96)
8. `2dp9A01` (100)
9. `1nktA02` (122)
10. `3mg3A01` (147)
11. `2incC00` (83)
12. `4nreA01` (120)
13. `1h4yA00` (115)
14. `2kjrA01` (80)
15. `4qncB00` (82)
16. `3aekA03` (123)
17. `2ji7A03` (212)
18. `3i01A03` (228)
19. `2izwC00` (208)
20. `2k54A00` (123)
21. `4pkiG02` (171)
22. `4b96A00` (151)
23. `4deqA02` (53)
24. `3pt1A02` (120)
25. `3atsA01` (116)
26. `3d8lA00` (91)
27. `3tdgA01` (66)
28. `1jeyB03` (102)

The first eight existing receipts may be reused only after their settings,
checkpoint identities, source transitions, and hashes pass the same aggregator
validation as newly generated receipts.

## Frozen transition and inference settings

- Role: validation only.
- Temperature: 450 K.
- Replicas: all five available replicas.
- Starts per replica: four deterministic evenly spaced starts.
- Transition lag: exactly 50 source frames within one replica.
- Stochastic samples per start: four.
- ODE steps per sample: ten.
- Inference seed: `20260801` for both source and candidate.
- Alignment and C-alpha metric implementation: unchanged from
  `dynaview-mars-fm-exact-lag-validation-v1`.
- Bootstrap unit: protein.
- Bootstrap resamples: 100,000.
- Bootstrap seed: `20260801`.

Best-of-four error is diagnostic only because selecting a sample using the
unknown future is not an inference-time capability. The primary score is the
ensemble-mean endpoint C-alpha RMSD.

## Frozen advancement gate

Anchor08 advances to multi-lag and kinetic validation only if all conditions
hold across the complete 28-protein population:

1. mean ensemble-endpoint RMSD improvement over source MarS-FM is positive and
   its protein-bootstrap 95% interval excludes zero;
2. at least 75% of proteins improve over source MarS-FM;
3. mean ensemble-endpoint RMSD improvement over coordinate persistence is
   positive and its protein-bootstrap 95% interval excludes zero;
4. at least 75% of proteins improve over coordinate persistence;
5. no source or candidate receipt uses a test record, crosses replicas, changes
   the lag, or disagrees on the exact transition population;
6. the candidate checkpoint and every receipt retain the immutable identities
   above.

No minimum practical effect size is inferred from this experiment. Even a pass
only establishes broad validation nonregression/improvement at one lag. The
later field-competitiveness gate must preregister a practically meaningful
effect threshold before matched competitor outputs are inspected.

## Failure and continuation policy

If any advancement condition fails, do not open standard test data and do not
delete proteins, change inference seeds, or relax the gate. Diagnose failures
on train/validation data under a fresh run identity. If the gate passes, freeze
the result and design the multi-lag, replica-noise, semigroup/kinetic, and
matched-competitor protocols before generating those outputs.

All generated arrays and receipts remain validation-only development evidence.
