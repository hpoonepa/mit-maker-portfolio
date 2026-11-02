# Handoff receipts

- `local-verification.json`: software test log, source hashes, syntax inspection,
  local dependency versions and confirmation that model modules were not imported.
- `experiment-plan.json`: generated plan, implementation hash, proposed budget
  and all uncompleted readiness flags. Both execution/spend authorization are false.
- `preflight.json`: full-experiment readiness is false. Its exit status of 2 is
  expected; it identifies future work rather than a failed scientific result.
- `research-inventory.json`: source/release evidence available at this handoff.
- `file-inventory.json`: SHA-256 inventory of the new package and associated plan.

No file here is a trained checkpoint, an executed model benchmark or a cloud
receipt. The USD 200 cap is proposed, and no provider bill was started.

The next session should first read the implementation plan and current receipts.
After model execution is authorized, resolve an isolated environment and run
`python -m dynamics.ember.model_checks.run_checks --execute-model` on CPU. Stop
and fix any failure before proceeding. That script was authored but not run here.
Then audit the original data, prepare frozen manifests and profile a few real
development systems before deciding whether a bulk feature run fits the budget.

Reuse the seven starting files under `configs/`; do not launch every combination.
The `crossfit-plan` command writes explicit outer prediction and inner selection
sets. Cached-feature training uses `train-residue` and `train-sites`; `predict`
accepts a reference-free bundle. Their help describes mandatory paths, and every
model command is disabled unless its explicit execution flag is supplied.

Move checkpoints by copying the whole run directory with relative symlinks
preserved. Use one training worker per output directory. Provider timeout,
shutdown, immutable storage and actual billing enforcement are still separate
compute-stage responsibilities.
