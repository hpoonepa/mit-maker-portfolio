"""Per-target dynamics pipeline. Called inside the Vast.ai container.

Inputs:  apo PDB id (downloaded), num_samples
Outputs: JSON file with ensemble sites, cryptic calls, and apo baseline.

This is integration glue over already-tested modules. End-to-end execution
requires BioEmu (GPU) + fpocket (in-container), neither available locally —
the cloud smoke test (plan Task 12) is its real validation.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from dynamics.datasets import fetch_pdb
from dynamics.ensemble import generate_ensemble, split_ensemble_pdb
from dynamics.pockets import detect_pockets
from dynamics.cluster import cluster_pockets_across_frames
from dynamics.cryptic import call_cryptic_pockets


def run(apo_pdb_id: str, work_dir: Path, num_samples: int = 100) -> dict:
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    apo_pdb = fetch_pdb(apo_pdb_id, work_dir / "apo")

    # 1. ensemble
    ensemble_dir = work_dir / "ensemble"
    multi = generate_ensemble(apo_pdb, ensemble_dir, num_samples=num_samples)
    frame_pdbs = split_ensemble_pdb(multi, work_dir / "frames")

    # 2. per-frame pockets
    per_frame = [detect_pockets(fp) for fp in frame_pdbs]

    # 3. cluster across frames
    sites = cluster_pockets_across_frames(per_frame, distance_threshold=4.0)

    # 4. apo baseline pockets
    apo_pockets = detect_pockets(apo_pdb)

    # 5. cryptic calls
    calls = call_cryptic_pockets(sites, apo_pockets, persistence_threshold=0.2)

    result = {
        "apo_pdb_id": apo_pdb_id,
        "num_frames": len(frame_pdbs),
        "ensemble_sites": [
            {
                "centroid": list(s.centroid),
                "persistence": s.persistence,
                "mean_volume": s.mean_volume,
                "mean_druggability": s.mean_druggability,
            }
            for s in sites
        ],
        "apo_baseline_pockets": [
            {"center": list(p.center), "volume": p.volume, "druggability": p.druggability}
            for p in apo_pockets
        ],
        "cryptic_calls": [
            {
                "centroid": list(c.site.centroid),
                "score": c.score,
                "persistence": c.site.persistence,
                "apo_match_distance": c.apo_match_distance,
            }
            for c in calls
        ],
    }
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apo-pdb-id", required=True)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--num-samples", type=int, default=100)
    ap.add_argument("--output-json", required=True, type=Path)
    args = ap.parse_args()
    result = run(args.apo_pdb_id, args.work_dir, args.num_samples)
    args.output_json.write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
