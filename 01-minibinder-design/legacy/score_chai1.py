"""Run Chai-1 structure predictions for the VP3 candidate panel.

Usage:
  python3 -m modal run score_chai1.py --designs-dir /tmp/designs"""

import modal
import os
from pathlib import Path

# VP3 surface domain (5MV5 Chain C, exposed region)
VP3_SURFACE_DOMAIN = (
    "LDADPFVEQRIEGTNPISLYWFAPVGVVSSMFMQWRGSLEYRFDIIASQFHTGRLIVGYVPGLTASLQLQMDYMKLKSSSYVV"
    "FDLQESNSFTFEVPYVSYRPWWVRKYGGNYLPSSTDAPSTLFMYVQVPLIPMEAVSDTIDINVYVRGGSSFEVCVPVQPSLGL"
    "NWNTDFILRNDEEYRAKTGYAPYYAGVWHSFNN"
)

GPU = os.environ.get("GPU", "A100")


def download_models():
    import torch
    from tempfile import TemporaryDirectory
    from chai_lab.chai1 import run_inference

    with TemporaryDirectory() as td_in, TemporaryDirectory() as td_out:
        with open(f"{td_in}/tmp.faa", "w") as out:
            out.write(
                ">protein|name=pro\nMAWTPLLLLLLSHCTGSLSQPVLTQPTSL\n"
                ">ligand|name=lig\nCC\n"
            )
        _ = run_inference(
            fasta_file=Path(f"{td_in}/tmp.faa"),
            output_dir=Path(f"{td_out}"),
            num_trunk_recycles=1,
            num_diffn_timesteps=10,
            seed=1,
            device=torch.device("cuda:0"),
            use_esm_embeddings=True,
        )


image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("wget")
    .uv_pip_install("chai_lab==0.6.1")
    .run_function(download_models, gpu="a100")
)

app = modal.App("5mv5-chai1-scoring", image=image)


@app.function(timeout=60 * 60, gpu=GPU)
def score_one(
    binder_seq: str,
    target_seq: str,
    design_id: str,
    seed: int = 42,
) -> dict:
    """Score a single binder-target complex with Chai-1."""
    import torch
    import numpy as np
    from tempfile import TemporaryDirectory
    from chai_lab.chai1 import run_inference

    fasta_content = f">protein|name=binder\n{binder_seq}\n>protein|name=target\n{target_seq}\n"

    with TemporaryDirectory() as td_in, TemporaryDirectory() as td_out:
        fasta_path = Path(td_in) / "complex.faa"
        fasta_path.write_text(fasta_content)

        candidates = run_inference(
            fasta_file=fasta_path,
            output_dir=Path(td_out),
            num_trunk_recycles=3,
            num_diffn_timesteps=200,
            seed=seed,
            device=torch.device("cuda:0"),
            use_esm_embeddings=True,
        )

        result = {
            "design_id": design_id,
            "sequence": binder_seq,
            "length": len(binder_seq),
        }

        # Extract scores from run_inference return value
        if candidates is not None:
            # StructureCandidates object — try common attributes
            for attr in dir(candidates):
                if not attr.startswith("_"):
                    print(f"    [{design_id}] candidates.{attr} = {type(getattr(candidates, attr))}")
            if hasattr(candidates, 'aggregate_score'):
                result["chai_ranking_score"] = float(candidates.aggregate_score)
            elif hasattr(candidates, 'scores'):
                result["chai_ranking_score"] = float(candidates.scores[0]) if len(candidates.scores) > 0 else None

        # Parse output files for detailed metrics
        out_dir = Path(td_out)

        # List all files to find the right ones
        all_files = list(out_dir.rglob("*"))
        print(f"    [{design_id}] Output files: {[str(f.name) for f in all_files if f.is_file()]}")

        # Try to find scores in npz files
        npz_files = list(out_dir.rglob("*.npz"))
        for npz_file in npz_files:
            data = np.load(npz_file, allow_pickle=True)
            keys = list(data.keys())
            print(f"    [{design_id}] NPZ keys: {keys}")
            if "ptm" in data:
                result["chai_ptm"] = float(data["ptm"])
            if "iptm" in data:
                result["chai_iptm"] = float(data["iptm"])
            if "plddt" in data:
                plddt = data["plddt"]
                result["chai_plddt_mean"] = float(plddt.mean())
                result["chai_binder_plddt"] = float(plddt[:len(binder_seq)].mean())

        # Also check for separate npy files
        for npy_file in out_dir.rglob("*.npy"):
            name = npy_file.stem
            data = np.load(npy_file, allow_pickle=True)
            if "plddt" in name:
                result["chai_plddt_mean"] = float(data.mean())
                result["chai_binder_plddt"] = float(data[:len(binder_seq)].mean())
            elif "pae" in name:
                # Extract interface PAE (binder rows, target cols)
                binder_len = len(binder_seq)
                if data.ndim >= 2 and data.shape[0] > binder_len:
                    interface_pae = data[:binder_len, binder_len:]
                    result["chai_interface_pae"] = float(interface_pae.mean())

        # Check for scores in JSON files
        for json_file in out_dir.rglob("*.json"):
            try:
                import json
                with open(json_file) as f:
                    jdata = json.load(f)
                if isinstance(jdata, dict):
                    for key in ["ptm", "iptm", "ipTM", "pTM", "ranking_score"]:
                        if key in jdata and key.lower().replace("i", "i") not in result:
                            result[f"chai_{key.lower()}"] = jdata[key]
            except Exception:
                pass

        return result


@app.local_entrypoint()
def main(
    designs_dir: str = "/tmp",
    output: str = "5mv5_chai1_scores.json",
):
    """
    Score all binder designs with Chai-1.

    Reads all designs_len*_surface_*.txt files from designs_dir,
    scores each with Chai-1, and writes ranked results.
    """
    import json
    import glob

    # Collect all designs (deduplicate by sequence)
    seen_seqs = set()
    designs = []
    for fasta_file in sorted(glob.glob(f"{designs_dir}/d*.txt")):
        with open(fasta_file) as f:
            lines = f.read().strip().split("\n")
        for i in range(0, len(lines), 2):
            if i + 1 < len(lines) and lines[i].startswith(">"):
                boltz_loss = float(lines[i][1:])
                seq = lines[i + 1].strip()
                if seq in seen_seqs:
                    continue
                seen_seqs.add(seq)
                length = len(seq)
                design_id = f"len{length}_{len(designs):03d}"
                designs.append({
                    "design_id": design_id,
                    "sequence": seq,
                    "boltz2_loss": boltz_loss,
                    "length": length,
                })

    print(f"\n{'='*60}")
    print(f"  CHAI-1 SCORING — {len(designs)} designs")
    print(f"  Target: VP3 surface domain (5MV5 Chain C)")
    print(f"  Estimated time: ~{len(designs) * 30 / 60:.0f} min on A100")
    print(f"{'='*60}\n")

    # Sort by Boltz-2 loss (best first) for progress tracking
    designs.sort(key=lambda d: d["boltz2_loss"])

    # Launch all scoring jobs in parallel via starmap
    arguments = [
        (d["sequence"], VP3_SURFACE_DOMAIN, d["design_id"])
        for d in designs
    ]

    results = []
    for i, result in enumerate(score_one.starmap(arguments)):
        # Merge Boltz-2 loss into result
        result["boltz2_loss"] = designs[i]["boltz2_loss"]
        results.append(result)

        iptm = result.get("chai_iptm", "N/A")
        if isinstance(iptm, float):
            iptm = f"{iptm:.3f}"
        print(f"  [{i+1}/{len(designs)}] {result['design_id']} "
              f"Boltz2={result['boltz2_loss']:.4f} "
              f"Chai_ipTM={iptm} "
              f"len={result['length']}")

    # Sort by Chai ipTM (best first)
    results.sort(key=lambda r: r.get("chai_iptm", 0) or 0, reverse=True)

    # Write results
    with open(output, "w") as f:
        json.dump(results, f, indent=2)

    # Print summary
    print(f"\n{'='*60}")
    print(f"  RESULTS — Ranked by Chai-1 ipTM")
    print(f"{'='*60}")
    print(f"  {'Rank':<5} {'ID':<12} {'Len':<5} {'Boltz2':<9} {'ipTM':<8} {'pTM':<8} {'pLDDT':<8}")
    print(f"  {'─'*5} {'─'*12} {'─'*5} {'─'*9} {'─'*8} {'─'*8} {'─'*8}")

    hits = 0
    for i, r in enumerate(results[:20]):
        iptm = r.get("chai_iptm", "N/A")
        ptm = r.get("chai_ptm", "N/A")
        plddt = r.get("chai_binder_plddt", "N/A")
        if isinstance(iptm, float):
            if iptm > 0.5:
                hits += 1
            iptm = f"{iptm:.3f}"
        if isinstance(ptm, float):
            ptm = f"{ptm:.3f}"
        if isinstance(plddt, float):
            plddt = f"{plddt:.3f}"
        print(f"  #{i+1:<4} {r['design_id']:<12} {r['length']:<5} "
              f"{r['boltz2_loss']:<9.4f} {iptm:<8} {ptm:<8} {plddt:<8}")

    print(f"\n  Designs with Chai ipTM > 0.5: {hits}/{len(results)}")
    print(f"  Results saved to: {output}")
    print(f"{'='*60}")
