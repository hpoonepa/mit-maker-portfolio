"""Modal app: Boltz2 independent cross-validation for Round 2 candidates.

Re-validates 24 PASS candidates from round2_filtered_candidates.csv
using our own Boltz2 inference. Compares against reported scores to
verify claims.

Usage:
    modal run --detach modal_boltz2_round2_v2.py"""

import modal
import pathlib
import csv

app = modal.App("rbx1-boltz2-round2-v2")

# Correct RBX1 target sequence (108aa) — differs from PDB 2LGV crystallization construct
TARGET_SEQ = "MAAAMDVDTPSGTNSGAGKKRFEVKKWNAVALWAWDIVVDNCAICRNHIMDLCIECQANQASATSEECTVAWGVCNHAFHFHCISRWLKTRQVCPLDNREWEFQKYGH"

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
        "src/minibinder/fold/validate_boltz2.py",
        remote_path="/opt/mosaic/validate_boltz2.py",
    )
)

# 24 PASS candidates from round2_filtered_candidates.csv (protenix_v2, 65aa)
CANDIDATES = {
    "v2_s2":  "SEFEEANKELKEAVTSDLPEEEREKVSKEAAEEVTEASYELIKEAGLPEPKSNEELSEAVREALA",
    "v2_s33": "SPLEEEVKELVEEALELGLELAEALAEAAAAKDPEEKEELEKEAEELEKEVDELNEEAKELIAQL",
    "v2_s11": "LEEEIEELQEEAKEVLDEMVEVVELEQEKGEDSPEVQEKREEVEKKKEEVSEKAKELKEKVEKLK",
    "v2_s12": "MSEEEKKKKKEEEELKKELAELLLENAELAEELAEEYEAAGDEEKAKEWEEKAEELEEAAEELLK",
    "v2_s22": "SMELELAELRLELAEEAVETAKAILAEIKASGAPDAAEKAAKAEETLEELEEKLEEAKKELEELE",
    "v2_s23": "SAEEEAKELREAAENAELVVEILEEMLEEAKKKNPPQEALDNGEEAIEELEEVAEEAREAAEELE",
    "v2_s9":  "VEELLEEAEKRLEEAEEELEEAREELEEAKKGSEEEREEAETELLLAEVRLELAEEAVEILEAAL",
    "v2_s36": "SLLEEAKKLLEEAMELAAEAFELLEEAESASEEEQEKAEKEVDELVEEAAELVEEAKKLEEEAEK",
    "v2_s37": "SAAEEEAKRYEESAELAEEIAERLREKAENSKSKDPADKEELLEHAEVMEEQAERLRKKAEELLA",
    "v2_s39": "SEAEEAEKKAEELAEEAKEVAAEARAAAQEGTEEGKKKAEELQAEVRELLDEIVEAVAKAQDLES",
    "v2_s32": "SMEEELREAAETGSREETREKIVEVANEAVEEAKKEKDPEKREEIIEEAEEAINEAERIVREKEA",
    "v2_s34": "SELEEAKKEYEEAAKEALEAYDALMEAIESGKASEEELEELVEELDEAVEELNEAKAELEELKAA",
    "v2_s27": "SEVEEAKKEVEEELEELEEAVERLADARAAGDEEAIKEADEELEEAAEEAREAAAELKEAVAAAA",
    "v2_s15": "GSAEEKEEAEKEVEEALAEAKAAAAAYAAAAADATASEAEKAAARAAFEAAMEELLEAVEELSAA",
    "v2_s1":  "SEKEELKKKLKELLEEALELIDEVAELEKEAEETISEEAAEEAEEAEEELDEAVKEANEVKEQLS",
    "v2_s20": "SAEEKKKKAEELLEKAEKLLEEAKKELEEAKKSGKASENELALLELQVEILSETVEKAKENVAAA",
    "v2_s13": "SALERVEKAVEESEKNTEEIVKKLEELLKTASEEDKEIIQQLLDAVKELYEEFKPYAEELLEKAK",
    "v2_s28": "SEKETLEEIAEVLEEMIEEAKKKVEEAKKKYKDDEEKQEKAEEAEKAVKEAKKKLEEIKEEAEEL",
    "v2_s19": "SAAAAYAARAAAAEEEAEELLKELEELAKEDPSLGLLLEVIESMEDPELALRMLELLLEQYEKEK",
    "v2_s25": "AEEKLKIAEEALEEVTKKLEEAKEELETEELSEQEREVLELTVELAEEAVKTAEALVAEAKAALA",
    "v2_s7":  "SEELEELKKKVEELLEEAEELREEAEEAEEEGEPLSEEEIETLLALAEVMLEIAERARKALEERE",
    "v2_s38": "SDEEQAERLERAVELAKDNPNLAEALAKLAEKLAADPSASEEAKERLREIAERAREVAEEAEAKL",
    "v2_s31": "SRETRLRNAEIIAEKYERTAEKLRAQAAEAEAAGDEEEAARLEALAEEYEAEAEEAREKAEELAA",
    "v2_s16": "SALEELEAEAAELAEEALDEVINAKTEEEHEKLAKEARELAAAAAAVVAAARAAAAAIAAAAAAA",
}


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=3600,
    volumes={"/mnt/weights": weights_volume},
)
def validate_single(candidate_id: str, sequence: str) -> dict:
    """Run Boltz2 validation for a single candidate."""
    import subprocess
    import os

    # Use candidate_id hash as seed for reproducibility
    seed = abs(hash(candidate_id)) % 1000000

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
        err_dir = f"/mnt/weights/boltz2_round2_v2/{candidate_id}"
        os.makedirs(err_dir, exist_ok=True)
        with open(f"{err_dir}/error.txt", "w") as f:
            f.write(result.stderr[-2000:])
        weights_volume.commit()
        return {"id": candidate_id, "error": result.stderr[-2000:]}

    # Parse CSV line
    csv_line = None
    for line in result.stdout.splitlines():
        if line.startswith("CSV:"):
            csv_line = line[4:]
            break

    outputs = {"id": candidate_id, "log": result.stdout, "csv_line": csv_line}

    # Save to volume
    vol_dir = f"/mnt/weights/boltz2_round2_v2/{candidate_id}"
    os.makedirs(vol_dir, exist_ok=True)
    with open(f"{vol_dir}/log.txt", "w") as f:
        f.write(result.stdout)
    if csv_line:
        with open(f"{vol_dir}/csv_line.txt", "w") as f:
            f.write(csv_line)

    # Save PDB
    pdb_path = f"/opt/mosaic/2lgv_boltz2_seed{seed:03d}.pdb"
    try:
        with open(pdb_path, "rb") as f:
            data = f.read()
        outputs["pdb"] = data
        with open(f"{vol_dir}/boltz2.pdb", "wb") as vf:
            vf.write(data)
    except FileNotFoundError:
        pass

    weights_volume.commit()
    print(f"{candidate_id}: saved to volume at {vol_dir}")
    return outputs


@app.local_entrypoint()
def main():
    """Launch Boltz2 re-validation for all 24 round 2 candidates."""
    print("=== RBX1 (2LGV) Boltz2 Round 2 Re-Validation ===")
    print(f"Candidates: {len(CANDIDATES)}")
    print(f"GPU: A100-80GB")
    print()

    args = [(cid, seq) for cid, seq in sorted(CANDIDATES.items())]
    results = list(validate_single.starmap(args))

    out = pathlib.Path("boltz2_round2_v2_outputs")
    out.mkdir(parents=True, exist_ok=True)

    successes = []
    failures = []

    for res in results:
        cid = res["id"]
        if "error" in res:
            failures.append(cid)
            print(f"  {cid}: FAILED")
            err_dir = out / cid
            err_dir.mkdir(exist_ok=True)
            (err_dir / "error.txt").write_text(res["error"])
            continue

        cid_dir = out / cid
        cid_dir.mkdir(exist_ok=True)
        (cid_dir / "log.txt").write_text(res.get("log", ""))
        if "pdb" in res:
            (cid_dir / "boltz2.pdb").write_bytes(res["pdb"])

        successes.append(res)
        print(f"  {cid}: OK")

    # Write summary CSV
    csv_path = out / "round2_revalidation.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "candidate_id", "boltz2_plddt", "boltz2_iptm",
            "boltz2_bt_ipsae", "boltz2_tb_ipsae", "boltz2_min_ipsae",
        ])
        for res in successes:
            if res.get("csv_line"):
                parts = res["csv_line"].split(",")
                # csv_line format: seed,plddt,iptm,bt_ipsae,tb_ipsae,min_ipsae
                writer.writerow([res["id"]] + parts[1:])

    print(f"\n=== Re-Validation Complete ===")
    print(f"Successes: {len(successes)}/{len(CANDIDATES)}")
    print(f"Failures: {len(failures)}/{len(CANDIDATES)}")
    print(f"Summary: {csv_path}")

    if successes:
        print(f"\n{'ID':>10s}  {'pLDDT':>7s}  {'ipTM':>7s}  {'bt_ip':>7s}  {'tb_ip':>7s}  {'min_ip':>7s}")
        for res in sorted(successes, key=lambda r: r["id"]):
            if res.get("csv_line"):
                p = res["csv_line"].split(",")
                if len(p) >= 6:
                    print(f"{res['id']:>10s}  {p[1]:>7s}  {p[2]:>7s}  {p[3]:>7s}  {p[4]:>7s}  {p[5]:>7s}")

    print(f"\nNext: python compare_round2.py")
