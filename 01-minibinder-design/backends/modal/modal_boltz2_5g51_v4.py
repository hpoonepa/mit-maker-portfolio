"""Modal app: Boltz2 cross-validation for 5G51 V4 candidates.

Validates 23 candidates (Protenix ipTM > 0.80) from 5G51 V4 campaign against PDB 5G51
using Boltz2 structure prediction.

Usage:
    modal run modal_boltz2_5g51_v4.py      # run attached — waits for all results + writes local CSV"""

import modal
import os

app = modal.App("5g51-v4-boltz2-validation")

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

# 23 candidates from 5G51 V4 campaign (Protenix ipTM > 0.80)
CANDIDATES = {
    6:  "MVEEMYNAWYGVVENTIKESEADTSLSEEEKKKQIRAAAETALNCVIAAAARVQTESTDEEEREEAARILRKALTEIKPKLEAAM",
    1:  "MTPEEETEDLRLTAINLANAAIAANNYYTEEEREKRGRAPEPVVEAYKLLKEAERDPEKAKELSAKAWEVHERAAKEAREAEAKR",
    17: "SVVDEYLEKLRNNEKPSAKQRENFEAAASPTEYMAAEMLKYALKVTKEAAKALKYGSEEEKKEARKALKTKAEPAQANAEEALAL",
    4:  "EIKYYSPEVIVLYVVAERAMEAYKKAKGKDPEVAKGAKELLEAAKKLGKEALKYNNSEDREKMKELTERTWKLAKRMKELEAAAA",
    5:  "SNVEKALELLEEAARIAAKDTGVFALSIVRMAKETVGKDLSEEEKKKILRLTAENMLELADNALSPEVKKKVKGLAEEAKEKATM",
    37: "SVEEKIREIWKEVGERVRAIRAEMEKNAEAAEEYAKKNNLDPAEAEKNAALYRQLAENAAAAYAVKKLRERVGELFTEEHVERAL",
    2:  "SEAEEEAKEANKKKAKAKKATAAALNFRERIREEARANWTPEVGEKAVELIYAAREAANAACDVWNEADAKVKEAEAALKEALFG",
    19: "STAEKIKNMTPADVVQALCTGSKEQNKQFVDNLIEYARKFVPPENREWAGKVADRLEEAKGLVTEGDMEEARKKASQAMAELMAL",
    22: "MEELVEEARKAEENGTTDTEPLFELADELERLAFELYVKARRTGSKELDRRAKRAFGAAESITEIGSKILKKAIEKAEKKVAELL",
    24: "SAAEARRERNKLRGKATAYVEEAKKVLNKPPTGPATMEERNWALDDLVCMVAKVEAAKTVEEAERLAEETKRRAEYAVAKANGEL",
    15: "SAKEKYKEYFKKAYKYALKVKEAMKYAAAPTPEEYRRARRATKALWKTMKKAKKECPEHEDKIKKLNELSMRAATATFLLMMALP",
    7:  "SEKAEKANKRLKGYAEATEEAAKAAREAKKAGDKEELRKRVVEATTAYQVAGAIVNAAKKKGVEVDKENRKEAEENLAEVMALAN",
    13: "SAEREEEEEKENLRQLLTYLFQMLQCANDPNYPNAEKERKLAAKIAKRIENTDPELVKEIAKDNPAMKEAAKRAKEYAAIARGEI",
    23: "FVAKMRKLYKIAKGFLKEAVELIDAARDLMNEVAKVTNTGEPPTAEEKEAMKLVYDANIAASAELKEALEKYREAKAAQEKAERE",
    30: "SAEEEKKEALDLATRIAAAKIRANMLEDAVREKAAKKYGDPNGPGAEELVANARERSPEVFGKVRELREEAMKIPGGREAIEKAE",
    39: "SKKERKKKARKIIKALMEINKKYPDVFSMTVNRMINILAATTPIMEKAKNNIAEACDSWLKMVEAYCPERKKAKEICKEIMALYE",
    20: "SERRKRLAAAAAKLMGRAEELLDMGEKAAKKMTAEAAEKATKGEATPEEVEAGLNKAKEAVENTRAYAKMMLDTAKEALIQAARA",
    34: "RAQAEKDLPKHRKQIKKTRKENKKRYEESKKKFEKFLEKHPRDPELAKKAKKEAEEAAKKYKSPYMQYWAFMTVAGKGAFKLLEP",
    27: "SVVDELRERARERAEARIRKKKRKLRKKAARARLDAEFAADIYARGAAYGAYMKEEWKKKKLEEKTEKATKELEEKIEKKVEELL",
    31: "AEAEFKEGMKGRKEIKAEVRKNRIKEVRRTYPVVTTDDPEEKEEARKRNDPEFQKLARFVASRIIAEACEPLTDKIHEATKALLA",
    0:  "EAAMAKKIIDDSTENVEANAANKARWLLDVAEEAEALIEKNKGDPAAQARAKRIKKIALALAKTVFIHAKAKYDELKKRLEAAVA",
    26: "MTWAQLEVNEKAKKIVEAAKKYPELKEEAEKAKEATREYNRAVRIAMLTHMEEGDRAWQKAGEAYKEAKKVVEEGLKAVEKAEKE",
    38: "AYSPQVMAAYKLYRAGDTEAAEEAVKEQTAEAEEAFAAGTEANRNDTSLSEEEKADAYAATEIEKARFRCILKIVAKMAEAKRAE",
}


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=7200,
    volumes={"/mnt/weights": weights_volume},
)
def validate_batch(seed_seq_pairs: list[list]) -> dict:
    """Run Boltz2 validation for a batch of candidates sequentially (amortizes JIT)."""
    import subprocess
    import shutil

    results = {}
    for pair in seed_seq_pairs:
        seed, sequence = int(pair[0]), pair[1]
        out_dir = f"/mnt/weights/boltz2_5g51_v4_outputs/seed_{seed:03d}"
        os.makedirs(out_dir, exist_ok=True)

        result = subprocess.run(
            ["/opt/mosaic/.venv/bin/python", "/opt/mosaic/validate_boltz2.py",
             str(seed), sequence, "5G51.cif"],
            cwd="/opt/mosaic",
            capture_output=True,
            text=True,
        )

        print(f"=== Seed {seed} ===")
        print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)

        if result.returncode != 0:
            with open(f"{out_dir}/error.txt", "w") as f:
                f.write(result.stdout + "\n" + result.stderr)
            results[seed] = "ERROR"
            continue

        # Save log
        with open(f"{out_dir}/log.txt", "w") as f:
            f.write(result.stdout)

        # Save CSV line
        for line in result.stdout.split("\n"):
            if line.startswith("CSV:"):
                csv_line = line[4:]
                with open(f"{out_dir}/csv_line.txt", "w") as f:
                    f.write(csv_line)
                results[seed] = csv_line

        # Save PDB
        pdb_path = f"/opt/mosaic/5g51_boltz2_seed{seed:03d}.pdb"
        if os.path.exists(pdb_path):
            shutil.copy2(pdb_path, f"{out_dir}/5g51_boltz2.pdb")

    weights_volume.commit()
    return results


@app.local_entrypoint()
def main():
    """Launch Boltz2 validation for 23 5G51 V4 candidates (attached mode)."""
    import csv as csv_mod

    items = sorted(CANDIDATES.items())
    batch_size = 3
    batches = []
    for i in range(0, len(items), batch_size):
        batch = [[str(seed), seq] for seed, seq in items[i:i + batch_size]]
        batches.append(batch)

    print(f"=== 5G51 V4 Boltz2 Cross-Validation ===")
    print(f"Candidates: {len(CANDIDATES)}")
    print(f"Batches: {len(batches)} (x{batch_size} seeds each)")
    print(f"GPUs: A100-80GB")
    print()

    all_results = {}
    for batch_results in list(validate_batch.map(batches)):
        all_results.update(batch_results)

    # Write combined CSV
    csv_path = "boltz2_5g51_v4_results.csv"
    header = ["seed", "boltz2_plddt", "boltz2_iptm", "boltz2_bt_ipsae", "boltz2_tb_ipsae", "boltz2_min_ipsae"]
    with open(csv_path, "w", newline="") as f:
        writer = csv_mod.writer(f)
        writer.writerow(header)
        for s in sorted(all_results.keys()):
            if all_results[s] != "ERROR":
                writer.writerow(all_results[s].split(","))

    ok = sum(1 for v in all_results.values() if v != "ERROR")
    print(f"\n=== VALIDATION COMPLETE ===")
    print(f"Completed: {ok}/{len(CANDIDATES)}")
    print(f"Local CSV: {csv_path}")
    print(f"Volume: modal volume ls mosaic-weights boltz2_5g51_v4_outputs/")
