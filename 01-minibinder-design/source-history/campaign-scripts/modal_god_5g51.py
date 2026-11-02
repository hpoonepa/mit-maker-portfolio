"""
Modal app for God-tier DWV-VP3 (5G51) minibinder design campaign.
Runs design_god_5g51.py across multiple seeds on A100 GPUs.

Usage:
    modal run modal_god.py                    # single random seed
    modal run modal_god.py --seed 42          # specific seed
    modal run modal_god.py --campaign 100     # batch: 100 seeds (0-99)
"""

import modal
import os

app = modal.App("god-5g51-campaign")

weights_volume = modal.Volume.from_name("mosaic-weights", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "curl", "build-essential")
    .pip_install("uv")
    .run_commands(
        # 1. Clone jopenfold3 and remove broken symlink
        "git clone https://github.com/escalante-bio/jopenfold3.git /tmp/jopenfold3",
        "rm -f /tmp/jopenfold3/jopenfold3/mosaic",
    )
    .run_commands(
        # 2. Clone mosaic and patch pyproject.toml for local jopenfold3
        "git clone https://github.com/escalante-bio/mosaic.git /opt/mosaic",
        "cd /opt/mosaic && sed -i "
        "'s|jopenfold3 = { git = \"https://github.com/escalante-bio/jopenfold3.git\" }|"
        "jopenfold3 = { path = \"/tmp/jopenfold3\" }|' pyproject.toml",
    )
    .run_commands(
        # 3. Download target structure and install deps
        "curl -o /opt/mosaic/5G51.cif 'https://files.rcsb.org/download/5G51.cif'",
        "cd /opt/mosaic && UV_HTTP_TIMEOUT=300 uv lock && UV_HTTP_TIMEOUT=300 uv sync --group jax-cuda",
    )
    .env({"XLA_PYTHON_CLIENT_MEM_FRACTION": "0.9"})
    # add_local_file MUST be last in the image build chain
    .add_local_file(
        "design_god_5g51.py",
        remote_path="/opt/mosaic/design_god_5g51.py",
    )
)


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=3600,
    volumes={"/mnt/weights": weights_volume},
)
def design_single(seed: int):
    """Run a single design with the given seed."""
    import subprocess
    import shutil

    out_dir = f"/mnt/weights/god_5g51_outputs/seed_{seed:03d}"
    os.makedirs(out_dir, exist_ok=True)

    result = subprocess.run(
        ["/opt/mosaic/.venv/bin/python", "/opt/mosaic/design_god_5g51.py", str(seed)],
        cwd="/opt/mosaic",
        capture_output=True,
        text=True,
    )

    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)

    if result.returncode != 0:
        with open(f"{out_dir}/error.txt", "w") as f:
            f.write(result.stdout + "\n" + result.stderr)
        weights_volume.commit()
        return {"seed": seed, "csv_line": "", "status": "error", "error": result.stderr[-2000:]}

    # Save all outputs to volume (survives client disconnect)
    for fname in ["god_complex.pdb", "god_pssm.png", "god_pae.png", "god_plddt.png"]:
        src = f"/opt/mosaic/{fname}"
        if os.path.exists(src):
            shutil.copy2(src, f"{out_dir}/{fname}")

    # Save CSV line
    csv_line = ""
    for line in result.stdout.split("\n"):
        if line.startswith("CSV:"):
            csv_line = line[4:]
            with open(f"{out_dir}/csv_line.txt", "w") as f:
                f.write(csv_line)

    # Save full log
    with open(f"{out_dir}/log.txt", "w") as f:
        f.write(result.stdout)

    weights_volume.commit()

    # Return only metadata (not large binary files)
    return {"seed": seed, "csv_line": csv_line, "status": "ok"}


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=7200,
    volumes={"/mnt/weights": weights_volume},
)
def design_batch(seeds: list[int]):
    """Run designs for a batch of seeds sequentially on one GPU (amortizes JIT)."""
    import subprocess
    import shutil

    results = {}
    for seed in seeds:
        out_dir = f"/mnt/weights/god_5g51_outputs/seed_{seed:03d}"
        os.makedirs(out_dir, exist_ok=True)

        result = subprocess.run(
            ["/opt/mosaic/.venv/bin/python", "/opt/mosaic/design_god_5g51.py", str(seed)],
            cwd="/opt/mosaic",
            capture_output=True,
            text=True,
        )

        print(f"=== Seed {seed} ===")
        # Print last 500 chars of output (skip JIT noise)
        print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)

        # Save outputs to volume
        for fname in ["god_complex.pdb", "god_pssm.png", "god_pae.png", "god_plddt.png"]:
            src = f"/opt/mosaic/{fname}"
            if os.path.exists(src):
                shutil.copy2(src, f"{out_dir}/{fname}")

        for line in result.stdout.split("\n"):
            if line.startswith("CSV:"):
                with open(f"{out_dir}/csv_line.txt", "w") as f:
                    f.write(line[4:])
                results[seed] = line[4:]

        with open(f"{out_dir}/log.txt", "w") as f:
            f.write(result.stdout)

    weights_volume.commit()
    return results


@app.local_entrypoint()
def main(seed: int = -1, campaign: int = 0):
    if campaign > 0:
        # Batch campaign: distribute seeds across GPUs
        # 5 seeds per GPU to amortize JIT compilation (~4 min)
        seeds = list(range(campaign))
        batch_size = 5
        batches = [seeds[i : i + batch_size] for i in range(0, len(seeds), batch_size)]

        print(f"=== GOD BINDER CAMPAIGN ===")
        print(f"Seeds: {campaign}")
        print(f"Batches: {len(batches)} (x{batch_size} seeds each)")
        print(f"GPUs: A100-80GB")
        print(f"Est. time: ~{10 + 5 * batch_size} min/batch, ~2.5h wall time")
        print(f"Est. cost: ~${campaign * 0.82:.0f}")
        print()

        all_results = {}
        for batch_results in design_batch.map(batches):
            all_results.update(batch_results)

        # Write combined CSV locally (best-effort — may not complete if detached)
        csv_header = "seed,sequence,length,cys_count,binder_plddt,target_plddt,iptm\n"
        csv_body = "".join(
            all_results[s] + "\n" for s in sorted(all_results.keys())
        )
        try:
            with open("god_campaign_results.csv", "w") as f:
                f.write(csv_header + csv_body)
            print(f"\nLocal CSV written: god_campaign_results.csv")
        except Exception:
            pass  # Client disconnected — results safe on volume

        print(f"\n=== CAMPAIGN COMPLETE ===")
        print(f"Designs completed: {len(all_results)}/{campaign}")
        print(f"Results on volume: modal volume ls mosaic-weights god_5g51_outputs/")
        print(f"Download: modal volume get mosaic-weights god_5g51_outputs/ ./god_5g51_outputs/")

    else:
        # Single seed
        if seed == -1:
            import random

            seed = random.randint(0, 999999)
        print(f"Running god-tier binder design with seed {seed}...")
        result = design_single.remote(seed)
        print(f"\nSeed {seed} complete: {result.get('status', 'unknown')}")
        if result.get("csv_line"):
            print(f"CSV: {result['csv_line']}")
        print(f"\nResults saved to volume. Download with:")
        print(f"  modal volume get mosaic-weights god_5g51_outputs/seed_{seed:03d}/ ./seed_{seed:03d}/")
