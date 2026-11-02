# Starting configurations

These JSON files instantiate the authored `TrainingConfig`. They are starting
settings for future tuning and execution. All use CPU as a conservative
default; the compute stage must choose and record a compatible environment.

- `linear-probe.json` and `r0.json`: matched frozen ESM-2 features, linear versus
  residue MLP. R0 class weighting is calculated on each fit's training records.
- `s0-linear.json` and `s0-mlp.json`: static ranker comparison.
- `e0-linear.json` and `e0-mlp.json`: correction on an already selected frozen S0.
- `e0-no-support-counts.json`: third E0 configuration. It defaults to linear;
  change `kind` to `ensemble_mlp` only if the declared development decision chose
  the MLP. Keep the chosen form and remove explicit frame/support counts.

Do not launch all combinations. Follow the staged decisions and reserve final
evaluation money. An E0 configuration needs `--base-release`; every fit needs
explicit training/development manifests and checksummed feature caches.

No configuration grants model-execution or cloud-spend permission.
