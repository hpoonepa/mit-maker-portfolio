# Nebius single-VM runner — 5G51 V4 campaign

Replaces the Modal `.map()` fan-out with one H100 VM running seeds sequentially.

## One-time prerequisites (you must do these — they cannot be automated)

1. **Install + authenticate the `nebius` CLI**, then run `nebius profile create`.
2. **Request H100 GPU quota** in the Nebius console (`gpu-h100-sxm`). New accounts
   have zero GPU quota — provisioning fails without it.
3. **Export the required IDs and SSH key path** before running any script:
   ```bash
   export NEBIUS_PROJECT_ID=<your project id>
   export NEBIUS_SUBNET_ID=<a subnet id in eu-north1>
   export NEBIUS_SSH_KEY=$HOME/.ssh/id_ed25519        # optional, this is the default
   export MOSAIC_REPO_URL=<git url of the mosaic repo> # OR plan to rsync (see below)
   ```

## Launch

```bash
# 1. Provision the H100 VM (creates disk + instance, prints IP + teardown command)
./nebius/provision.sh

# 2. Build the Docker images on the VM
#    If the mosaic repo has no git remote, instead rsync the working tree:
#    rsync -az -e "ssh -i $NEBIUS_SSH_KEY" --exclude .venv --exclude nebius/outputs \
#      ./ ubuntu@$(cat nebius/.state/instance_ip):/opt/mosaic-src/
./nebius/build.sh

# 3. Run the design campaign (seed 0 runs first as a gate, then seeds 1..49)
python -m nebius.run_campaign --host $(cat nebius/.state/instance_ip) --seeds 50

# 4. Run Boltz2 validation over the 23 candidates
python -m nebius.run_validation --host $(cat nebius/.state/instance_ip)

# 5. TEARDOWN — destroy the VM (the run scripts print the exact command)
nebius compute instance delete --id $(cat nebius/.state/instance_id)
```

## Resume after interruption

Both runners checkpoint after every seed. Re-run with `--resume` to continue:
```bash
python -m nebius.run_campaign --host <IP> --seeds 50 --resume
```
Inspect partial progress with the existing `vast/resume.py` — the checkpoint JSON
files in `nebius/checkpoints/` use the same format.

## Outputs

- `nebius/outputs/5g51_v4/seed_NNN/` — per-seed PDB, plots, logs, csv_line.txt
- `nebius/outputs/5g51_v4/5g51_v4_campaign_results.csv` — merged design results
- `nebius/outputs/boltz2_5g51_v4/boltz2_5g51_v4_results.csv` — merged validation results

## Cost

H100 on-demand ≈ $2.50–3.50/hr. Full 50-seed design ≈ 6.5 GPU-hrs ≈ $20–25.
The seed-0 gate caps a broken-pipeline cost at ~$3.

## Note on the Python interpreter

This machine has no `python` on PATH and system `python3` is 3.9. The runner
modules require Python 3.12 — use `nebius/.venv/bin/python -m nebius.run_campaign ...`
(and likewise for `run_validation`) if a bare `python` is unavailable.
