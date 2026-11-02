"""Modal app: Boltz2 cross-validation for 5G51 COMBINED candidates.

Validates 12 pooled candidates from two 5G51 campaigns (V4 + V3b) against PDB 5G51
using Boltz2 structure prediction. Namespaced keys avoid seed-number collisions
between campaigns.

Usage:
    modal run scripts/modal_boltz2_5g51_combined.py   # run attached — waits for all results + writes local CSV"""

import modal
import os

app = modal.App("5g51-combined-boltz2-validation")

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
        "src/minibinder/fold/validate_boltz2.py",
        remote_path="/opt/mosaic/validate_boltz2.py",
    )
)

# 12 pooled candidates from 5G51 V4 + V3b campaigns.
# Namespaced keys: v4_* from 5g51_v4_boltz2_candidates.csv (85aa), v3b_* from god_v3b_results.csv (65aa)
CANDIDATES = {
    "v4_1":   "MTPEEETEDLRLTAINLANAAIAANNYYTEEEREKRGRAPEPVVEAYKLLKEAERDPEKAKELSAKAWEVHERAAKEAREAEAKR",
    "v4_17":  "SVVDEYLEKLRNNEKPSAKQRENFEAAASPTEYMAAEMLKYALKVTKEAAKALKYGSEEEKKEARKALKTKAEPAQANAEEALAL",
    "v4_37":  "SVEEKIREIWKEVGERVRAIRAEMEKNAEAAEEYAKKNNLDPAEAEKNAALYRQLAENAAAAYAVKKLRERVGELFTEEHVERAL",
    "v4_5":   "SNVEKALELLEEAARIAAKDTGVFALSIVRMAKETVGKDLSEEEKKKILRLTAENMLELADNALSPEVKKKVKGLAEEAKEKATM",
    "v3b_29": "DAEELKEELEKKTEELKEELKKEVGSEEAAEAALKDPSNPLVQEARPELQKLADEILDLLIEELL",
    "v3b_1":  "MSPKEHEAELLLFSAEVLLRAAKLLLERAKKTPEKIEELLEKAEELEEEAEELREEAEELEEELE",
    "v3b_19": "SELDKKIDEIVEEAKKKIKELLAKIEELKKTLKPTPEDEKKIEELQEKAQEAAEEALDKIIELLL",
    "v3b_15": "SEEELKKKELEVALEFLTGLLEEAEEKKKKGEPVNEKLVELAKEKLKELLTEILGSEEKAKELLK",
    "v3b_18": "SRELLSEAAEFAAERAKELAEEAKENGDENKRKAALNLAKKLLESGLIKDEEKREKLEEIVEELS",
    "v3b_10": "MSEIAKFLAGRLAELLGLDLSPEEAAERLGDLSPEEARELARAAGQSPAQVEVAGKLAELVRELR",
    "v3b_48": "NAEMEELKKELSKALKELLDLRIELLSTELELPEEAQKKAEELEKEVEETEEETKELKEKLKKLE",
    "v3b_16": "SEYDELLEEAKELAKEAGKLGKEAAELREEYPDDPEAQARAAKLRAEAEKLAKEALELFDEALSL",
}


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=14400,
    volumes={"/mnt/weights": weights_volume},
)
def run_all(candidates: list[list]) -> dict:
    """Run Boltz2 validation for ALL candidates inside ONE remote container.

    Self-contained: loops every candidate, runs validate_boltz2.py, writes per-seed
    outputs AND the combined results CSV to the volume, committing after each seed.
    Nothing depends on the local client surviving — launch with `modal run --detach`
    so the run finishes even if the local connection drops mid-run.

    Each item is [idx, label, sequence]. validate_boltz2.py requires an INTEGER seed
    (used as a JAX RNG key and in {:03d} pdb naming), so the integer idx is passed to
    it; the namespaced label (e.g. v4_1, v3b_29) is used for all output keys, volume
    dirs, and the CSV first column.
    """
    import subprocess
    import shutil
    import csv as csv_mod

    base = "/mnt/weights/boltz2_5g51_combined_outputs"
    os.makedirs(base, exist_ok=True)
    results = {}

    for idx, label, sequence in candidates:
        out_dir = f"{base}/seed_{label}"
        os.makedirs(out_dir, exist_ok=True)

        result = subprocess.run(
            ["/opt/mosaic/.venv/bin/python", "/opt/mosaic/validate_boltz2.py",
             str(idx), sequence, "5G51.cif"],
            cwd="/opt/mosaic",
            capture_output=True,
            text=True,
        )

        print(f"=== {label} (idx {idx}) rc={result.returncode} ===")
        print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)

        if result.returncode != 0:
            with open(f"{out_dir}/error.txt", "w") as f:
                f.write(result.stdout + "\n" + result.stderr)
            results[label] = "ERROR"
            weights_volume.commit()
            continue

        with open(f"{out_dir}/log.txt", "w") as f:
            f.write(result.stdout)

        # Swap validate_boltz2.py's numeric idx for the namespaced label
        for line in result.stdout.split("\n"):
            if line.startswith("CSV:"):
                fields = line[4:].split(",")
                fields[0] = label
                results[label] = ",".join(fields)
                with open(f"{out_dir}/csv_line.txt", "w") as f:
                    f.write(results[label])

        pdb_path = f"/opt/mosaic/5g51_boltz2_seed{idx:03d}.pdb"
        if os.path.exists(pdb_path):
            shutil.copy2(pdb_path, f"{out_dir}/5g51_boltz2.pdb")

        weights_volume.commit()  # persist progress after every seed

    # Combined results CSV — written to the volume so no local client is needed
    header = ["seed", "boltz2_plddt", "boltz2_iptm", "boltz2_bt_ipsae", "boltz2_tb_ipsae", "boltz2_min_ipsae"]
    with open(f"{base}/boltz2_5g51_combined_results.csv", "w", newline="") as f:
        w = csv_mod.writer(f)
        w.writerow(header)
        for label in sorted(results):
            if results[label] != "ERROR":
                w.writerow(results[label].split(","))
    weights_volume.commit()

    ok = sum(1 for v in results.values() if v != "ERROR")
    print(f"\n=== RUN COMPLETE: {ok}/{len(candidates)} succeeded ===")
    return results


@app.local_entrypoint()
def main(only: str = ""):
    """Dispatch the combined Boltz2 run as ONE remote, detach-safe call.

    `only` — optional comma-separated labels to run a subset (e.g. --only v4_1).
             idx is computed from the full sorted candidate list, so a label's
             integer seed is stable whether run alone or in the full batch.

    Launch detached so the run survives a local client disconnect:
        modal run --detach scripts/modal_boltz2_5g51_combined.py
        modal run --detach scripts/modal_boltz2_5g51_combined.py --only v4_1

    Results land in the volume at:
        boltz2_5g51_combined_outputs/boltz2_5g51_combined_results.csv
    """
    items = sorted(CANDIDATES.items())
    indexed = [[idx, label, seq] for idx, (label, seq) in enumerate(items)]
    if only:
        wanted = {x.strip() for x in only.split(",")}
        indexed = [t for t in indexed if t[1] in wanted]
    candidates = indexed

    print(f"=== 5G51 COMBINED Boltz2 Cross-Validation ===")
    print(f"Candidates: {len(candidates)}  {[c[1] for c in candidates]}")
    print(f"GPU: A100-80GB  |  single-container remote orchestration, detach-safe")
    print()

    run_all.spawn(candidates)
    print("run_all dispatched (fire-and-forget). Monitor / collect with:")
    print("  modal app list")
    print("  modal volume ls mosaic-weights boltz2_5g51_combined_outputs/")
