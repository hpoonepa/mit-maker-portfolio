"""
Vast.ai: Boltz2 independent cross-validation for Round 2 candidates.

Re-validates 24 PASS candidates from round2_filtered_candidates.csv
using our own Boltz2 inference on Vast.ai instances. Equivalent of
modal_boltz2_round2.py but using Vast.ai orchestrator.

Usage:
    python -m vast.vast_boltz2_round2
    python -m vast.vast_boltz2_round2 --output-dir /path/to/output
    python -m vast.vast_boltz2_round2 --no-resume --max-concurrent 6
"""

import argparse
import csv
import pathlib

from . import orchestrator
from . import config

# Correct RBX1 target sequence (108aa) — differs from PDB 2LGV crystallization construct
TARGET_SEQ = "MAAAMDVDTPSGTNSGAGKKRFEVKKWNAVALWAWDIVVDNCAICRNHIMDLCIECQANQASATSEECTVAWGVCNHAFHFHCISRWLKTRQVCPLDNREWEFQKYGH"

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


def main():
    parser = argparse.ArgumentParser(
        description="Boltz2 Round 2 re-validation on Vast.ai",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="vast_boltz2_round2_outputs",
        help="Directory for output files (default: vast_boltz2_round2_outputs/)",
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Resume from checkpoint (default: True, use --no-resume to restart)",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=None,
        help=f"Max simultaneous instances (default: {config.MAX_CONCURRENT})",
    )
    args = parser.parse_args()

    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=== RBX1 (2LGV) Boltz2 Round 2 Re-Validation (Vast.ai) ===")
    print(f"Candidates: {len(CANDIDATES)}")
    print(f"GPU: {config.GPU_NAME}")
    print(f"Resume: {args.resume}")
    print()

    # Launch validation across Vast.ai instances
    results = orchestrator.starmap_candidates(
        campaign_id="rbx1-boltz2-round2",
        docker_image=config.DOCKER_IMAGE_BOLTZ2,
        candidates=CANDIDATES,
        target_seq=TARGET_SEQ,
        output_dir=str(output_dir),
        max_concurrent=args.max_concurrent,
        resume=args.resume,
    )

    # Separate successes and failures
    successes = [r for r in results if "error" not in r]
    failures = [r for r in results if "error" in r]

    # Write summary CSV
    csv_path = output_dir / "round2_revalidation.csv"
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
    print(f"Failures:  {len(failures)}/{len(CANDIDATES)}")
    print(f"Summary:   {csv_path}")

    # Print results table
    if successes:
        print(f"\n{'ID':>10s}  {'pLDDT':>7s}  {'ipTM':>7s}  {'bt_ip':>7s}  {'tb_ip':>7s}  {'min_ip':>7s}")
        for res in sorted(successes, key=lambda r: r["id"]):
            if res.get("csv_line"):
                p = res["csv_line"].split(",")
                if len(p) >= 6:
                    print(f"{res['id']:>10s}  {p[1]:>7s}  {p[2]:>7s}  {p[3]:>7s}  {p[4]:>7s}  {p[5]:>7s}")

    if failures:
        print(f"\nFailed candidates:")
        for res in failures:
            print(f"  {res['id']}: {res.get('error', 'unknown')[:80]}")

    print(f"\nNext: python compare_round2.py")


if __name__ == "__main__":
    main()
