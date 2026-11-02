"""
Modal app: 5G51 minibinder design campaign on GPU.

Runs the exact Protenix2025 + ProteinMPNN + simplex_APGM workflow
from the RBX1 campaign, targeting PDB 5G51. Launches N seeds in
parallel via Modal's .map() for batch binder generation.

Usage:
    modal run modal_5g51.py                    # 50 seeds (default)
    modal run modal_5g51.py --num-seeds 100    # 100 seeds
"""

import modal
import pathlib
import csv
import io

app = modal.App("5g51-binder-campaign")

# Persistent volume for model weights (Protenix, etc.)
weights_volume = modal.Volume.from_name("mosaic-weights", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "curl", "build-essential")
    .pip_install("uv")
    .run_commands(
        # 1. Clone jopenfold3 and remove the broken absolute symlink
        #    (jopenfold3/mosaic -> /home/ubuntu/of3/... which doesn't exist)
        "git clone https://github.com/escalante-bio/jopenfold3.git /tmp/jopenfold3",
        "rm -f /tmp/jopenfold3/jopenfold3/mosaic",
    )
    .run_commands(
        # 2. Clone mosaic and patch pyproject.toml to use local jopenfold3
        "git clone https://github.com/escalante-bio/mosaic.git /opt/mosaic",
        "cd /opt/mosaic && sed -i "
        "'s|jopenfold3 = { git = \"https://github.com/escalante-bio/jopenfold3.git\" }|"
        "jopenfold3 = { path = \"/tmp/jopenfold3\" }|' pyproject.toml",
    )
    .run_commands(
        # 3. Regenerate lockfile with patched source, then install everything
        #    uv sync applies override-dependencies from pyproject.toml
        #    (forces scipy==1.15.1, resolving the protenix conflict)
        "cd /opt/mosaic && uv lock && uv sync --group jax-cuda",
    )
    .run_commands(
        # 4. Download target structure
        "curl -fsSL -o /opt/mosaic/5G51.cif https://files.rcsb.org/download/5G51.cif",
    )
    .env({"XLA_PYTHON_CLIENT_MEM_FRACTION": "0.9"})
    # add_local_file MUST be last in the image build chain
    .add_local_file(
        "design_5g51.py",
        remote_path="/opt/mosaic/design_5g51.py",
    )
)


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=3600,
    volumes={"/mnt/weights": weights_volume},
)
def design_single(seed: int) -> dict:
    """Run a single binder design with the given seed."""
    import subprocess

    result = subprocess.run(
        ["/opt/mosaic/.venv/bin/python", "/opt/mosaic/design_5g51.py", str(seed)],
        cwd="/opt/mosaic",
        capture_output=True,
        text=True,
    )

    # Always print output for Modal logs
    print(result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout)
    if result.stderr:
        print(f"STDERR: {result.stderr[-500:]}")

    if result.returncode != 0:
        return {"seed": seed, "error": result.stderr[-2000:]}

    # Parse the CSV summary line from stdout
    csv_line = None
    for line in result.stdout.splitlines():
        if line.startswith("CSV:"):
            csv_line = line[4:]
            break

    outputs = {
        "seed": seed,
        "log": result.stdout,
        "csv_line": csv_line,
    }

    for fname in ["5g51_complex.pdb", "5g51_pssm.png", "5g51_pae.png", "5g51_plddt.png"]:
        path = f"/opt/mosaic/{fname}"
        try:
            with open(path, "rb") as f:
                outputs[fname] = f.read()
        except FileNotFoundError:
            pass

    weights_volume.commit()
    return outputs


@app.local_entrypoint()
def main(num_seeds: int = 50):
    """Launch a binder design campaign with N parallel seeds."""
    print(f"=== 5G51 Binder Design Campaign ===")
    print(f"Seeds: {num_seeds}")
    print(f"GPU: A100-80GB")
    print(f"Target: PDB 5G51 (VP3 P-domain, Deformed Wing Virus)")
    print(f"Binder length: 75 residues")
    print(f"Pipeline: Protenix2025 + ProteinMPNN + simplex_APGM")
    print()

    seeds = list(range(num_seeds))

    print(f"Launching {num_seeds} designs in parallel on Modal...")
    results = list(design_single.map(seeds))

    # Create output directory
    out = pathlib.Path("modal_outputs_5g51")
    out.mkdir(parents=True, exist_ok=True)

    # Collect results
    successes = []
    failures = []

    for res in results:
        seed = res["seed"]

        if "error" in res:
            failures.append(seed)
            print(f"  seed={seed}: FAILED")
            # Save error log
            err_dir = out / f"seed_{seed:03d}"
            err_dir.mkdir(exist_ok=True)
            (err_dir / "error.txt").write_text(res["error"])
            continue

        # Save output files
        seed_dir = out / f"seed_{seed:03d}"
        seed_dir.mkdir(exist_ok=True)
        (seed_dir / "log.txt").write_text(res.get("log", ""))

        for fname in ["5g51_complex.pdb", "5g51_pssm.png", "5g51_pae.png", "5g51_plddt.png"]:
            if fname in res:
                (seed_dir / fname).write_bytes(res[fname])

        successes.append(res)
        print(f"  seed={seed}: OK -> {seed_dir}")

    # Write summary CSV
    csv_path = out / "campaign_summary.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "seed", "sequence", "length", "cys_count",
            "binder_plddt", "target_plddt", "iptm",
        ])
        for res in successes:
            if res.get("csv_line"):
                writer.writerow(res["csv_line"].split(","))

    print(f"\n=== Campaign Complete ===")
    print(f"Successes: {len(successes)}/{num_seeds}")
    print(f"Failures: {len(failures)}/{num_seeds}")
    print(f"Summary CSV: {csv_path}")
    print(f"Results: {out}/")

    # Quick quality summary
    if successes:
        print(f"\n=== Quality Preview ===")
        for res in successes:
            if res.get("csv_line"):
                parts = res["csv_line"].split(",")
                if len(parts) >= 7:
                    print(f"  seed={parts[0]:>3s}  pLDDT={parts[4]}  ipTM={parts[6]}  cys={parts[3]}")

    print(f"\nNext: filter candidates with Boltz2 cross-validation (same as RBX1)")
