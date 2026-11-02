"""Modal orchestrator for V5 minibinder design + consensus validation.

End-to-end pipeline per seed:
    1. Design (design_v5.py) — ProtenixV2 + MPNN + v5 losses -> binder sequence + PDB
    2. Validate (validators/boltz2_consensus.py) — Boltz2 best-of-5 + Chai-1 consensus
       + post-hoc RMSD_binder and (optional) PyRosetta Shape Complementarity

Image mirrors modal_boltz2_5g51_v4.py (jopenfold3 + mosaic uv-sync with jax-cuda)
and additionally installs chai_lab for the consensus step. PyRosetta is NOT
installed by default (requires license acceptance); the SC step skips cleanly
when it's absent.

Usage:
    # Single seed end-to-end
    modal run src/modal_design_v5.py::run_one --seed 42 --target-cif 5G51.cif

    # Batch campaign (attached — waits for all + writes local CSV)
    modal run src/modal_design_v5.py --seeds 1,2,3,4,5 --target-cif 5G51.cif

    # Design-only (skip validation)
    modal run src/modal_design_v5.py --seeds 1,2,3 --skip-validate
"""

import csv as csv_mod
import os

import modal


app = modal.App("mosaic-v5-design")

weights_volume = modal.Volume.from_name("mosaic-weights", create_if_missing=True)


# ---------------------------------------------------------------------------
# Image build
# ---------------------------------------------------------------------------
#
# 1. Clone jopenfold3 + mosaic, patch mosaic pyproject to point at local jopenfold3
# 2. uv sync with jax-cuda extras
# 3. Download target CIFs into image (campaign scripts can override)
# 4. Install chai_lab for consensus (can be disabled by passing --skip-chai1 through)
# 5. Add local v5 files (src/, validators/, config/)
#
# CRITICAL: the first 6 layers below (through `.env XLA_PYTHON_CLIENT_MEM_FRACTION`)
# are bit-identical to modal_boltz2_5g51_v4.py's image spec. This lets Modal's
# global layer cache reuse v4's working image (last-built 2026-03-30 and still
# functional) — avoiding a fresh `git clone mosaic.git main` which now hits an
# upstream breakage (protenix pkl ShapeDtypeStruct.vma error).
#
# Do NOT reorder, rename, or add env vars above the v5-specific section without
# rebuilding the entire stack.
#
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
        # Pin to bca3152 (2026-04-07): first commit with ProtenixV2(), before the
        # 8362af3 refactor that added `required-environments` to pyproject.toml and
        # restructured protenix.py — that refactor is what triggers the fresh-build
        # ShapeDtypeStruct.vma pkl incompatibility at HEAD.
        "cd /opt/mosaic && git checkout bca3152",
        "cd /opt/mosaic && sed -i "
        "'s|jopenfold3 = { git = \"https://github.com/escalante-bio/jopenfold3.git\" }|"
        "jopenfold3 = { path = \"/tmp/jopenfold3\" }|' pyproject.toml",
    )
    .run_commands(
        # Pin jax==0.9.0 to match the version protenij serialised its .skeleton.pkl
        # with. jax 0.10.0 removed the `vma` attribute from ShapeDtypeStruct,
        # breaking pickle.load of protenij weights. See smoke-test run 2026-04-23.
        "cd /opt/mosaic && "
        "sed -i 's|\"jax>=0.8.1\"|\"jax==0.9.1\"|' pyproject.toml && "
        "uv lock && uv sync --group jax-cuda",
    )
    .run_commands(
        "curl -fsSL -o /opt/mosaic/5G51.cif https://files.rcsb.org/download/5G51.cif",
    )
    .env({"XLA_PYTHON_CLIENT_MEM_FRACTION": "0.9"})
    # --- V5-specific layers (new, rebuild fresh on top of cached v4 base) ---
    .run_commands(
        "curl -fsSL -o /opt/mosaic/2LGV.cif https://files.rcsb.org/download/2LGV.cif || true",
    )
    # Add v5 code tree under /opt/v5 — separate from /opt/mosaic/src/mosaic
    # (mosaic package). design_v5.py and boltz2_consensus.py do their own
    # sys.path.insert so `from src.losses.X` resolves under /opt/v5.
    .add_local_dir("src", remote_path="/opt/v5/src")
    .add_local_dir("validators", remote_path="/opt/v5/validators")
    .add_local_dir("config", remote_path="/opt/v5/config")
)


# ---------------------------------------------------------------------------
# Remote functions
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=600,
    volumes={"/mnt/weights": weights_volume},
)
def smoke_test() -> dict:
    """Tiny load-test: import ProtenixV2 and instantiate. Fails fast if the
    pinned mosaic commit can't unpickle weights with the resolved JAX version."""
    import subprocess
    result = subprocess.run(
        [
            "/opt/mosaic/.venv/bin/python", "-c",
            "from mosaic.models.protenix import ProtenixV2; "
            "m = ProtenixV2(); "
            "print('OK: ProtenixV2 loaded', type(m).__name__)",
        ],
        cwd="/opt/mosaic",
        capture_output=True,
        text=True,
    )
    print("STDOUT:", result.stdout[-2000:])
    if result.returncode != 0:
        print("STDERR:", result.stderr[-3000:])
        return {"status": "FAIL", "stderr": result.stderr[-3000:]}
    return {"status": "OK", "stdout": result.stdout[-500:]}


@app.local_entrypoint()
def smoke():
    """Run the smoke test before launching the real campaign."""
    print("=== V5 smoke test: ProtenixV2 load check ===")
    r = smoke_test.remote()
    print(r)
    if r["status"] != "OK":
        raise SystemExit(1)


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=3600,
    volumes={"/mnt/weights": weights_volume},
)
def design_seed(seed: int, target_cif: str, config_yaml: str = "config/v5_default.yaml") -> dict:
    """Run design_v5.py for a single seed. Returns metadata + CSV line + paths.

    Outputs land under /mnt/weights/v5_outputs/seed_{seed}/ for persistence.
    """
    import subprocess
    import shutil

    out_dir = f"/mnt/weights/v5_outputs/seed_{seed:03d}"
    os.makedirs(out_dir, exist_ok=True)

    result = subprocess.run(
        [
            "/opt/mosaic/.venv/bin/python",
            "/opt/v5/src/design_v5.py",
            "--seed", str(seed),
            "--target-structure", target_cif,
            "--config", f"/opt/v5/{config_yaml}",
            "--output-dir", out_dir,
        ],
        cwd="/opt/mosaic",   # cwd stays in mosaic for relative target_cif (e.g. 5G51.cif) lookup
        capture_output=True,
        text=True,
    )

    print(f"=== DESIGN seed={seed} ===")
    tail = result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout
    print(tail)
    if result.returncode != 0:
        print("STDERR tail:", result.stderr[-1000:])
        with open(f"{out_dir}/error.txt", "w") as f:
            f.write(result.stdout + "\n\nSTDERR:\n" + result.stderr)
        weights_volume.commit()
        return {"seed": seed, "status": "ERROR", "csv": None, "sequence": None, "pdb_path": None}

    # Extract CSV line and sequence from stdout
    csv_line = None
    sequence = None
    for line in result.stdout.split("\n"):
        if line.startswith("CSV:"):
            csv_line = line[4:]
            parts = csv_line.split(",")
            if len(parts) >= 2:
                sequence = parts[1]
    with open(f"{out_dir}/design_log.txt", "w") as f:
        f.write(result.stdout)

    pdb_path = f"{out_dir}/seed_{seed:03d}_complex.pdb"
    weights_volume.commit()
    return {
        "seed": seed,
        "status": "OK",
        "csv": csv_line,
        "sequence": sequence,
        "pdb_path": pdb_path,
    }


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=3600,
    volumes={"/mnt/weights": weights_volume},
)
def validate_seed(
    seed: int,
    sequence: str,
    target_cif: str,
    designed_pdb: str,
    skip_chai1: bool = False,
    skip_sc: bool = True,  # PyRosetta off by default (license)
) -> dict:
    """Run validators/boltz2_consensus.py for a single seed."""
    import subprocess

    out_dir = f"/mnt/weights/v5_outputs/seed_{seed:03d}/validation"
    os.makedirs(out_dir, exist_ok=True)

    cmd = [
        "/opt/mosaic/.venv/bin/python",
        "/opt/v5/validators/boltz2_consensus.py",
        "--seed", str(seed),
        "--sequence", sequence,
        "--target-cif", target_cif,
        "--designed-pdb", designed_pdb,
        "--output-dir", out_dir,
    ]
    if skip_chai1:
        cmd.append("--skip-chai1")
    if skip_sc:
        cmd.append("--skip-sc")

    result = subprocess.run(cmd, cwd="/opt/mosaic", capture_output=True, text=True)

    print(f"=== VALIDATE seed={seed} ===")
    tail = result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout
    print(tail)
    if result.returncode not in (0, 2):  # 2 = fail gate but successful run
        print("STDERR tail:", result.stderr[-1000:])
        with open(f"{out_dir}/error.txt", "w") as f:
            f.write(result.stdout + "\n\nSTDERR:\n" + result.stderr)
        weights_volume.commit()
        return {"seed": seed, "status": "ERROR", "csv": None}

    csv_line = None
    for line in result.stdout.split("\n"):
        if line.startswith("CSV:"):
            csv_line = line[4:]
    with open(f"{out_dir}/validate_log.txt", "w") as f:
        f.write(result.stdout)

    weights_volume.commit()
    return {"seed": seed, "status": "OK", "csv": csv_line, "passed_gate": result.returncode == 0}


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

@app.local_entrypoint()
def run_one(seed: int, target_cif: str = "5G51.cif", skip_validate: bool = False):
    """Single seed end-to-end: design then validate."""
    design_result = design_seed.remote(seed, target_cif)
    print("\n== Design result ==")
    print(design_result)
    if design_result["status"] != "OK" or skip_validate:
        return
    val = validate_seed.remote(
        seed, design_result["sequence"], target_cif, design_result["pdb_path"]
    )
    print("\n== Validation result ==")
    print(val)


@app.local_entrypoint()
def main(
    seeds: str = "1,2,3",
    target_cif: str = "5G51.cif",
    skip_validate: bool = False,
    skip_chai1: bool = True,    # Chai-1 not installed in image (see image-build note)
    skip_sc: bool = True,
):
    """Batch campaign: design N seeds in parallel, then validate each.

    Writes combined design + validation CSVs locally after all seeds complete.
    """
    seed_list = [int(s.strip()) for s in seeds.split(",") if s.strip()]
    print(f"=== V5 Campaign | {len(seed_list)} seeds | target={target_cif} ===")

    # --- Design wave ---
    design_results = list(design_seed.starmap([(s, target_cif) for s in seed_list]))
    design_csv = "v5_design_results.csv"
    design_header = ["seed", "sequence", "binder_len", "cys_count",
                     "binder_plddt", "target_plddt", "iptm"]
    with open(design_csv, "w", newline="") as f:
        w = csv_mod.writer(f)
        w.writerow(design_header)
        for r in design_results:
            if r["status"] == "OK" and r["csv"]:
                w.writerow(r["csv"].split(","))
    print(f"Wrote {design_csv} ({sum(1 for r in design_results if r['status'] == 'OK')} OK / {len(seed_list)})")

    if skip_validate:
        return

    # --- Validation wave (only for designs that succeeded) ---
    val_inputs = []
    for r in design_results:
        if r["status"] == "OK" and r["sequence"]:
            val_inputs.append((
                r["seed"], r["sequence"], target_cif, r["pdb_path"],
                skip_chai1, skip_sc,
            ))
    if not val_inputs:
        print("No successful designs to validate.")
        return
    val_results = list(validate_seed.starmap(val_inputs))

    val_csv = "v5_validation_results.csv"
    val_header = ["seed", "passes_gate", "boltz2_min_ipsae", "chai1_min_ipsae",
                  "consensus_min_ipsae", "rmsd_binder", "sc"]
    with open(val_csv, "w", newline="") as f:
        w = csv_mod.writer(f)
        w.writerow(val_header)
        for r in val_results:
            if r["status"] == "OK" and r["csv"]:
                w.writerow(r["csv"].split(","))
    passed = sum(1 for r in val_results if r.get("passed_gate"))
    print(f"Wrote {val_csv} ({passed} passed consensus gate / {len(val_results)} validated)")
    print(f"Modal volume: modal volume ls mosaic-weights v5_outputs/")
