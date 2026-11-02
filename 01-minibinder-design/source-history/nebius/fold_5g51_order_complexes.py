"""
Modal app: Co-fold 12 binder+target complexes with Boltz2 for the 5G51 (DWV VP3) order.

Reuses the PROVEN image from modal_boltz2_5g51_v4_run.py, but passes "5G51.cif"
(NOT a sequence) as the 3rd arg to validate_boltz2.py, with cwd=/opt/mosaic.
Designs are read from nebius/outputs/5g51_combined_order.csv (12 rows; 3 that
already have structures are skipped). Each complex PDB is downloaded locally.

Usage:
    modal run nebius/fold_5g51_order_complexes.py                      # all 12
    modal run nebius/fold_5g51_order_complexes.py --only 5G51_V4_seed01  # subset
"""

import modal
import csv
import pathlib

app = modal.App("5g51-order-boltz2-complexes")

weights_volume = modal.Volume.from_name("mosaic-weights", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "curl", "build-essential")
    .pip_install("uv")
    .run_commands(
        "git clone https://github.com/escalante-bio/jopenfold3.git /tmp/jopenfold3",
        "rm -f /tmp/jopenfold3/jopenfold3/mosaic",
    )
    .run_commands(
        "git clone https://github.com/escalante-bio/mosaic.git /opt/mosaic",
        "cd /opt/mosaic && sed -i "
        "'s|jopenfold3 = { git = \"https://github.com/escalante-bio/jopenfold3.git\" }|"
        "jopenfold3 = { path = \"/tmp/jopenfold3\" }|' pyproject.toml",
    )
    .run_commands(
        "cd /opt/mosaic && uv lock && uv sync --group jax-cuda",
    )
    .run_commands(
        "curl -fsSL -o /opt/mosaic/5G51.cif https://files.rcsb.org/download/5G51.cif",
    )
    .env({"XLA_PYTHON_CLIENT_MEM_FRACTION": "0.9"})
    .add_local_file(
        "validate_boltz2.py",
        remote_path="/opt/mosaic/validate_boltz2.py",
    )
)

CSV_PATH = pathlib.Path(__file__).parent / "outputs" / "5g51_combined_order.csv"
LOCAL_OUT = pathlib.Path(__file__).parent / "outputs" / "5g51_order_complexes"
SKIP_NAMES = {"5G51_V5_seed00_rank2", "5G51_V5_seed07_rank3", "5G51_V5_seed10_rank4"}
VOL_BASE = "/mnt/weights/boltz2_5g51_order_outputs"


@app.function(
    image=image,
    gpu="L40S",
    timeout=3600,
    volumes={"/mnt/weights": weights_volume},
)
def validate_single(name: str, seed: int, sequence: str) -> dict:
    """Co-fold one binder+target complex against 5G51.cif and save the PDB."""
    import subprocess
    import os

    result = subprocess.run(
        ["/opt/mosaic/.venv/bin/python", "/opt/mosaic/validate_boltz2.py",
         str(seed), sequence, "5G51.cif"],
        cwd="/opt/mosaic",
        capture_output=True,
        text=True,
    )

    tail = result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout
    print(tail)
    if result.stderr:
        print(f"STDERR: {result.stderr[-500:]}")

    vol_dir = f"{VOL_BASE}/{name}"
    os.makedirs(vol_dir, exist_ok=True)

    if result.returncode != 0:
        err = result.stderr[-2000:]
        with open(f"{vol_dir}/error.txt", "w") as f:
            f.write(err)
        weights_volume.commit()
        return {"name": name, "seed": seed, "error": err}

    # Parse the "CSV:" metrics line from stdout
    csv_line = None
    for line in result.stdout.splitlines():
        if line.startswith("CSV:"):
            csv_line = line[4:]
            break

    with open(f"{vol_dir}/log.txt", "w") as f:
        f.write(result.stdout)
    if csv_line:
        with open(f"{vol_dir}/csv_line.txt", "w") as f:
            f.write(csv_line)

    pdb_path = f"/opt/mosaic/5g51_boltz2_seed{seed:03d}.pdb"
    try:
        with open(pdb_path, "rb") as f:
            data = f.read()
        with open(f"{vol_dir}/complex.pdb", "wb") as vf:
            vf.write(data)
    except FileNotFoundError:
        pass

    weights_volume.commit()
    print(f"{name} (seed={seed}): saved to volume at {vol_dir}")
    # Return only small fields — never the pdb bytes (avoids flaky large-payload return).
    return {"name": name, "seed": seed, "csv_line": csv_line, "ok": True}


def _load_designs():
    """Read the 12 designs (excluding the 3 already-structured) from the CSV."""
    designs = []
    with open(CSV_PATH, newline="") as f:
        for row in csv.DictReader(f):
            if row["name"] in SKIP_NAMES:
                continue
            designs.append((row["name"], int(row["seed"]), row["sequence"]))
    return designs


def _pull_from_volume(name: str):
    """Download complex.pdb (+ log.txt) for one design from the Modal volume."""
    import subprocess

    d = LOCAL_OUT / name
    d.mkdir(parents=True, exist_ok=True)
    ok = False
    for fname in ("complex.pdb", "log.txt"):
        subprocess.run(
            ["modal", "volume", "get", "mosaic-weights",
             f"boltz2_5g51_order_outputs/{name}/{fname}",
             str(d / fname), "--force"],
            check=False,
        )
        if fname == "complex.pdb":
            ok = (d / "complex.pdb").exists()
    return ok


@app.local_entrypoint()
def main(only: str = ""):
    """Co-fold the order complexes (or a --only subset) and download PDBs from the volume."""
    designs = _load_designs()
    if only:
        wanted = {n.strip() for n in only.split(",") if n.strip()}
        designs = [d for d in designs if d[0] in wanted]

    # Idempotent: skip designs that already have a local complex.pdb.
    todo, skipped = [], []
    for name, seed, seq in designs:
        if (LOCAL_OUT / name / "complex.pdb").exists():
            skipped.append(name)
        else:
            todo.append((name, seed, seq))

    print("=== 5G51 Order Boltz2 Complex Co-Folding ===")
    print(f"Designs: {len(designs)}  To fold: {len(todo)}  Already local: {len(skipped)}  GPU: L40S")
    for name, seed, _ in todo:
        print(f"  fold  {name} (seed={seed})")
    for name in skipped:
        print(f"  skip  {name} (local complex.pdb exists)")
    print()

    LOCAL_OUT.mkdir(parents=True, exist_ok=True)
    statuses = {}  # name -> "OK" | "FAIL"

    args = [(name, seed, seq) for name, seed, seq in todo]
    if args:
        results = validate_single.starmap(args, return_exceptions=True)
        order = [name for name, _, _ in todo]
        for name, res in zip(order, results):
            if isinstance(res, Exception):
                print(f"  remote error  {name}: {res!r}")
                statuses[name] = "FAIL"
            elif isinstance(res, dict) and "error" in res:
                (LOCAL_OUT / name).mkdir(parents=True, exist_ok=True)
                (LOCAL_OUT / name / "error.txt").write_text(res["error"])
                statuses[name] = "FAIL"
            else:
                statuses[name] = "OK"

    # Download every PDB from the VOLUME (not from return bytes).
    print("\n=== Downloading PDBs from volume ===")
    for name, _, _ in designs:
        if statuses.get(name) == "FAIL":
            continue
        if _pull_from_volume(name):
            print(f"  pulled  {name}/complex.pdb")
        else:
            print(f"  missing {name}/complex.pdb on volume")

    print("\n=== Per-Design Summary ===")
    pdb_count = 0
    for name, seed, _ in designs:
        has_pdb = (LOCAL_OUT / name / "complex.pdb").exists()
        if has_pdb:
            pdb_count += 1
        flag = "OK  " if has_pdb else "FAIL"
        print(f"  {flag}  {name} (seed={seed})")

    print(f"\n=== Complete ===")
    print(f"PDBs present locally: {pdb_count}/{len(designs)}")
    print(f"Output dir: {LOCAL_OUT}/")
    print(f"Output dir: {LOCAL_OUT}/")
