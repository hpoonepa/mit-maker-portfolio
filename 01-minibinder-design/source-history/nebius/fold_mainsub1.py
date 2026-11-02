"""
Modal app: Co-fold mainsub1 binder+target complexes with Boltz2 for 5G51 (DWV VP3).

Reuses the PROVEN image + validate_single from fold_5g51_order_complexes.py, passing
"5G51.cif" as arg3 to validate_boltz2.py (cwd=/opt/mosaic). Designs come from
/Users/harsha/Downloads/mainsub1.csv (columns: name,sequence). Seed = 0-based row index
(unique, deterministic). Four designs are COPIED from already-folded 5g51_order_complexes
outputs instead of re-folding; the rest fold on Modal. Each PDB is pulled from the volume.

Usage:
    modal run nebius/fold_mainsub1.py                   # 4 copied, 11 folded
    modal run nebius/fold_mainsub1.py --only latent_03  # subset
"""

import modal
import csv
import pathlib
import shutil
import subprocess

app = modal.App("5g51-mainsub1-boltz2-complexes")

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

CSV_PATH = pathlib.Path("/Users/harsha/Downloads/mainsub1.csv")
LOCAL_OUT = pathlib.Path(__file__).parent / "outputs" / "mainsub1_complexes"
ORDER_OUT = pathlib.Path(__file__).parent / "outputs" / "5g51_order_complexes"
VOL_BASE = "/mnt/weights/boltz2_mainsub1_outputs"

# Designs to reuse from already-folded order complexes: {mainsub1 name -> source name}.
REUSE_FROM = {
    "5G51_V4_seed01": "5G51_V4_seed01",
    "5G51_V4_seed05_cysfree": "5G51_V4_seed05_cysfree",
    "latent_01": "5G51_ext_seq60",
    "latent_02": "5G51_ext_seq51",
}


@app.function(
    image=image,
    gpu="L40S",
    timeout=3600,
    volumes={"/mnt/weights": weights_volume},
)
def validate_single(name: str, seed: int, sequence: str) -> dict:
    """Co-fold one binder+target complex against 5G51.cif and save the PDB to the volume."""
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
    """Read (name, seed=row_index, sequence) from mainsub1.csv."""
    designs = []
    with open(CSV_PATH, newline="") as f:
        for i, row in enumerate(csv.DictReader(f)):
            designs.append((row["name"], i, row["sequence"]))
    return designs


def _pull_from_volume(name: str):
    """Download complex.pdb (+ log.txt) for one design from the Modal volume."""
    d = LOCAL_OUT / name
    d.mkdir(parents=True, exist_ok=True)
    ok = False
    for fname in ("complex.pdb", "log.txt"):
        subprocess.run(
            ["modal", "volume", "get", "mosaic-weights",
             f"boltz2_mainsub1_outputs/{name}/{fname}",
             str(d / fname), "--force"],
            check=False,
        )
        if fname == "complex.pdb":
            ok = (d / "complex.pdb").exists()
    return ok


def _copy_reused():
    """Copy already-folded complexes into mainsub1 output dirs instead of re-folding."""
    for name, src_name in REUSE_FROM.items():
        dst = LOCAL_OUT / name / "complex.pdb"
        if dst.exists():
            continue
        src = ORDER_OUT / src_name / "complex.pdb"
        if not src.exists():
            print(f"  WARN    reuse source missing: {src}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        src_log = ORDER_OUT / src_name / "log.txt"
        if src_log.exists():
            shutil.copy2(src_log, LOCAL_OUT / name / "log.txt")
        print(f"  copied  {name} <- {src_name}/complex.pdb")


@app.local_entrypoint()
def main(only: str = ""):
    """Co-fold mainsub1 complexes (or a --only subset); reuse 4, fold the rest, pull from volume."""
    LOCAL_OUT.mkdir(parents=True, exist_ok=True)
    designs = _load_designs()
    if only:
        wanted = {n.strip() for n in only.split(",") if n.strip()}
        designs = [d for d in designs if d[0] in wanted]

    # Copy reused structures BEFORE building the fold list so the idempotent skip excludes them.
    print("=== Reusing already-folded complexes ===")
    _copy_reused()

    # Idempotent skip: designs with a local complex.pdb (incl. just-copied) are not folded.
    todo, skipped = [], []
    for name, seed, seq in designs:
        if (LOCAL_OUT / name / "complex.pdb").exists():
            skipped.append(name)
        else:
            todo.append((name, seed, seq))

    print("\n=== 5G51 mainsub1 Boltz2 Complex Co-Folding ===")
    print(f"Designs: {len(designs)}  To fold: {len(todo)}  Already local: {len(skipped)}  GPU: L40S")
    for name, seed, _ in todo:
        print(f"  fold  {name} (seed={seed})")

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

    # Download every folded PDB from the VOLUME (copied ones already exist locally).
    print("\n=== Downloading folded PDBs from volume ===")
    for name, _, _ in todo:
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
    print(f"Complex PDBs present locally: {pdb_count}/{len(designs)}  ({LOCAL_OUT}/)")
