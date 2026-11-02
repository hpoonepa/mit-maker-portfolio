"""
Modal app: Boltz2 cross-validation for 5G51 (DWV-VP3) candidates.

Validates 22 candidates (ipTM > 0.75) from God 5G51 campaign
using Boltz2 structure prediction. Computes pLDDT, ipTM, ipSAE, min_ipSAE.

Results saved to Modal volume (mosaic-weights/boltz2_5g51_outputs/).

Usage:
    modal run --detach modal_boltz2_5g51.py
"""

import modal
import pathlib
import csv

TARGET_SEQ = "EEYRAKTGYAPYYAGVWHSFNNSNSLVFRWGSASDQIAQWPTISVPRGELAFLRIKDGKQAAVGTQPWRTMVVWPSGHGYNIGIPTYNAERARQLAQHLYGGGSLTDEKAKQLFVPANQQGPGKVSNGNPVWEVMRAPLATQRAHIQDFEFIEAIPE"

app = modal.App("5g51-boltz2-validation")

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
        "curl -fsSL -o /opt/mosaic/2LGV.cif https://files.rcsb.org/download/2LGV.cif",
    )
    .env({"XLA_PYTHON_CLIENT_MEM_FRACTION": "0.9"})
    .add_local_file(
        "validate_boltz2.py",
        remote_path="/opt/mosaic/validate_boltz2.py",
    )
)

# 22 candidates from God 5G51 campaign (ipTM > 0.75)
CANDIDATES = {
    2:  "SALDAVKEADRRLAKASEKLETEPLDPEKKEKAREKIEELGTNGGLTPEELLEGAEEVDELVEEA",
    4:  "SVEEAANEAFEATVELVALMVRAWKAARRDPSLRAEAEEVSEEADEELKERGKELAEKAKKLIAA",
    5:  "MSPEEVVEAAREAYEGDGSAEEAAKVSDAAYEAVQNASPEERERVREALRLAVNAWFRAKAREQA",
    6:  "AAVAAAKAAYAAAKAAKPAANAASQAASASGDLAAAIAATDALALAMVAYWKAEWALYEAKKAAE",
    8:  "SRAARRARIAKAVAEIMEKNYKPFVEAVLAVDPARLAAFKAAQAAAKTPEERAAVIAEALAELMA",
    9:  "LLEELLAARTGEEVAEAAVRLARAYSPEELSEEEAFKLMSEACIGNPEAFDEAEEAWEEVKELLS",
    11: "LKEKINELEKKMQEALKVINEAAKKYPGVMRTTDPEAQAATAEAEAAEKLLREADKKAEALRAAL",
    18: "LKEELEKKGKELEQTIKEAEEAIEKYEPYVGTGDLMAQDAVEAAKAAIEHAEKELKELKKKLKEL",
    19: "SDLEEGEELAKEHPEVGGVAREVAEEAVKEGLSPAEVVDRLAFRVSDEKLAKAVEIADLLVKALK",
    21: "AEAAARAAIAEAATAEIEELLEKLKKNPSLELVEEAAAAAAEAAVASGDISYLPETDDRIKEALS",
    23: "FAAAAAEAAKAAAAAAGGAVVAVCVAISEAWKAGKATEEITVALVEAVAAEVRATKALVAAEKAL",
    24: "SAAVAEARAATAEAEAAAAAATAAARAATAANGGEPRIDEEATVAANYAADDAVYNYLAAEAAAA",
    26: "ALSDEEKANKSIRMTVEREDPDGKKTTVETMISFDVDGTVWNAGSASEEVIEAARGLMKKAGLCK",
    28: "SLVEKAKTRAIKMMFTCGLSPEEVLERLERSVGRATKRVKDPENKKLLEEIREAVEEFLTEFAKM",
    29: "LEERIEELKREVRRAYRAMMEATAALIFGDPKTSSEEWEALTEEAREARERFKEAMRRLRELYLA",
    33: "SAAAAAAEAELAAASKESAAAVAELMKKWRTASPEEREKLDKELRAVCEELGKKVLEAEAKVKAA",
    34: "AAREALEAAAAASAALAEALNALAATTDPEEKAALNAKAEAALPAANAADAAAAAAFKAFDEARR",
    38: "SLEELKKLVGELTERIIRLCSLVVVDFETGEVEPVQANTDPRAQAAVEKAARIIKKLYKKVKELE",
    39: "SAAEKEAEALAAFEAKVAEAMAAAAEKLAAAKAAGKVYMLPDHPADKALNEVTEAAAAEANAAIA",
    41: "MRPVTRATLEEYKAKLEGGTATEEERERARRAARIALERAWEHYDHPGAQRLYLLAFIVALPPEE",
    46: "SELEELAEEARKASKEEATKLFFEYAPLAREAAARAEREGTEEARERHKKLREVVMAASEVMTKE",
    47: "RYYVTIIGIGRTEQDGDRQETIVAFFVVDDDGNVTVRPARVYATTEEEAKEATERAARALVERER",
}


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=3600,
    volumes={"/mnt/weights": weights_volume},
)
def validate_single(seed: int, sequence: str) -> dict:
    """Run Boltz2 validation for a single candidate."""
    import subprocess
    import os

    result = subprocess.run(
        ["/opt/mosaic/.venv/bin/python", "/opt/mosaic/validate_boltz2.py",
         str(seed), sequence, TARGET_SEQ],
        cwd="/opt/mosaic",
        capture_output=True,
        text=True,
    )

    print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
    if result.stderr:
        print(f"STDERR: {result.stderr[-500:]}")

    if result.returncode != 0:
        err_dir = f"/mnt/weights/boltz2_5g51_outputs/seed_{seed:03d}"
        os.makedirs(err_dir, exist_ok=True)
        with open(f"{err_dir}/error.txt", "w") as f:
            f.write(result.stderr[-2000:])
        weights_volume.commit()
        return {"seed": seed, "error": result.stderr[-2000:]}

    # Parse CSV line
    csv_line = None
    for line in result.stdout.splitlines():
        if line.startswith("CSV:"):
            csv_line = line[4:]
            break

    outputs = {"seed": seed, "log": result.stdout, "csv_line": csv_line}

    # Save to volume for resilience
    vol_dir = f"/mnt/weights/boltz2_5g51_outputs/seed_{seed:03d}"
    os.makedirs(vol_dir, exist_ok=True)
    with open(f"{vol_dir}/log.txt", "w") as f:
        f.write(result.stdout)
    if csv_line:
        with open(f"{vol_dir}/csv_line.txt", "w") as f:
            f.write(csv_line)

    # Save PDB structure
    pdb_path = f"/opt/mosaic/2lgv_boltz2_seed{seed:03d}.pdb"
    try:
        with open(pdb_path, "rb") as f:
            data = f.read()
        outputs["pdb"] = data
        with open(f"{vol_dir}/2lgv_boltz2.pdb", "wb") as vf:
            vf.write(data)
    except FileNotFoundError:
        pass

    weights_volume.commit()
    print(f"seed={seed}: saved to volume at {vol_dir}")
    return outputs


@app.local_entrypoint()
def main():
    """Launch Boltz2 validation for 22 God 5G51 candidates (ipTM > 0.75)."""
    print("=== DWV-VP3 (5G51) Boltz2 Cross-Validation ===")
    print(f"Candidates: {len(CANDIDATES)}")
    print(f"GPU: A100-80GB")
    print(f"Seeds: {sorted(CANDIDATES.keys())}")
    print()

    # Launch all validations in parallel via .starmap()
    args = [(seed, seq) for seed, seq in sorted(CANDIDATES.items())]
    results = list(validate_single.starmap(args))

    # Collect results locally
    out = pathlib.Path("boltz2_5g51_outputs_local")
    out.mkdir(parents=True, exist_ok=True)

    successes = []
    failures = []

    for res in results:
        seed = res["seed"]

        if "error" in res:
            failures.append(seed)
            print(f"  seed={seed}: FAILED")
            err_dir = out / f"seed_{seed:03d}"
            err_dir.mkdir(exist_ok=True)
            (err_dir / "error.txt").write_text(res["error"])
            continue

        seed_dir = out / f"seed_{seed:03d}"
        seed_dir.mkdir(exist_ok=True)
        (seed_dir / "log.txt").write_text(res.get("log", ""))
        if "pdb" in res:
            (seed_dir / "2lgv_boltz2.pdb").write_bytes(res["pdb"])

        successes.append(res)
        print(f"  seed={seed}: OK -> {seed_dir}")

    # Write summary CSV
    csv_path = out / "boltz2_summary.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "seed", "boltz2_plddt", "boltz2_iptm",
            "boltz2_bt_ipsae", "boltz2_tb_ipsae", "boltz2_min_ipsae",
        ])
        for res in successes:
            if res.get("csv_line"):
                writer.writerow(res["csv_line"].split(","))

    print(f"\n=== Validation Complete ===")
    print(f"Successes: {len(successes)}/{len(CANDIDATES)}")
    print(f"Failures: {len(failures)}/{len(CANDIDATES)}")
    print(f"Summary CSV: {csv_path}")
    print(f"Results: {out}/")

    # Print results table
    if successes:
        print(f"\n=== Results ===")
        print(f"{'seed':>5s}  {'pLDDT':>7s}  {'ipTM':>7s}  {'bt_ipSAE':>9s}  {'tb_ipSAE':>9s}  {'min_ip':>7s}")
        for res in sorted(successes, key=lambda r: r["seed"]):
            if res.get("csv_line"):
                p = res["csv_line"].split(",")
                if len(p) >= 6:
                    print(f"  {p[0]:>3s}  {p[1]:>7s}  {p[2]:>7s}  {p[3]:>9s}  {p[4]:>9s}  {p[5]:>7s}")

    print(f"\nNext: python filter_rbx1.py")
