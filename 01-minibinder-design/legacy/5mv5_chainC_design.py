"""Design VP3 binders with Mosaic and compare their predicted complexes with Protenix.

Adapted from Escalante Bio's Nipah competition winner.

Target: VP3 surface domain from Deformed Wing Virus (PDB: 5MV5, Chain C)
        ~175 residues (exposed region)

Usage:
  # Full pipeline: design 100 binders + score all with Protenix
  uvx modal run 5mv5_chainC_design.py

  # Score existing designs only
  uvx modal run 5mv5_chainC_design.py --score-only --input-fasta designs.txt"""

import modal

# ============================================================================
# 5MV5 CHAIN C TARGET — VP3 (Deformed Wing Virus)
# ============================================================================
# Full VP3 sequence (416 AA) from PDB 5MV5 Chain C
VP3_FULL = (
    "DNPSYQQSPRHFVPTGMHSLALGTNLVEPLHALRLDAAGTTQHPVGCAPDEDMTVSSIASRYGLIRRVQWKKDHAKGSLLLQ"
    "LDADPFVEQRIEGTNPISLYWFAPVGVVSSMFMQWRGSLEYRFDIIASQFHTGRLIVGYVPGLTASLQLQMDYMKLKSSSYVV"
    "FDLQESNSFTFEVPYVSYRPWWVRKYGGNYLPSSTDAPSTLFMYVQVPLIPMEAVSDTIDINVYVRGGSSFEVCVPVQPSLGL"
    "NWNTDFILRNDEEYRAKTGYAPYYAGVWHSFNNSNSLVFRWGSASDQIAQWPTISVPRGELAFLRIKDGKQAAVGTQPWRTMVV"
    "WPSGHGYNIGIPTYNAERARQLAQHLYGGGSLTDEKAKQLFVPANQQGPGKVSNGNPVWEVMRAPLATQRAHIQDFEFIEAIPE"
)

# Surface-exposed region for focused design (roughly residues 80-260)
# The main exposed surface loop/domain of VP3 — what a binder can actually reach
VP3_SURFACE_DOMAIN = (
    "LDADPFVEQRIEGTNPISLYWFAPVGVVSSMFMQWRGSLEYRFDIIASQFHTGRLIVGYVPGLTASLQLQMDYMKLKSSSYVV"
    "FDLQESNSFTFEVPYVSYRPWWVRKYGGNYLPSSTDAPSTLFMYVQVPLIPMEAVSDTIDINVYVRGGSSFEVCVPVQPSLGL"
    "NWNTDFILRNDEEYRAKTGYAPYYAGVWHSFNN"
)

# ============================================================================
# MODAL IMAGE FOR BOLTZ-2 DESIGN
# ============================================================================
def download_boltz2():
    from mosaic.models.boltz2 import Boltz2
    Boltz2()


boltz_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .run_commands("git clone https://github.com/escalante-bio/mosaic.git")
    .workdir("mosaic")
    .run_commands("uv pip install --system -r pyproject.toml")
    .run_commands("uv pip install --system jax[cuda]")
    .run_commands("uv pip install --system .")
    .run_function(download_boltz2)
    .run_commands("uv pip install --system equinox")
    .env({"XLA_PYTHON_CLIENT_MEM_FRACTION": "0.95"})
)

# ============================================================================
# MODAL IMAGE FOR PROTENIX SCORING
# ============================================================================
protenix_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "wget")
    .run_commands("pip install protenix")
    # NOTE: protenix download needs CUDA (compiles fused kernels on import),
    # so we download model weights at runtime where GPU is available.
    .env({"PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"})
)

app = modal.App("5mv5-vp3-binder-design")
vol = modal.Volume.from_name("5mv5-vp3-binders", create_if_missing=True)


# ============================================================================
# STAGE 1: BOLTZ-2 DESIGN
# ============================================================================
@app.function(
    image=boltz_image,
    gpu="A100-80GB",
    timeout=int(12 * 60 * 60),
    volumes={"/structures": vol},
)
def design_boltz2(
    max_runtime_seconds: int,
    binder_length: int = 100,
    use_surface_domain: bool = True,
):
    """
    Generate binder designs for 5MV5 VP3 using Boltz-2 hallucination.
    Writes checkpoint files to the shared volume after every design.
    """
    import uuid
    import time
    import jax
    import jax.numpy as jnp
    import equinox as eqx
    import numpy as np

    from mosaic.models.boltz2 import Boltz2
    import mosaic.losses.structure_prediction as sp
    from mosaic.common import TOKENS
    from mosaic.losses.protein_mpnn import InverseFoldingSequenceRecovery
    from mosaic.losses.transformations import NoCys
    from mosaic.proteinmpnn.mpnn import load_mpnn_sol
    from mosaic.structure_prediction import TargetChain
    from mosaic.optimizers import simplex_APGM

    TARGET_SEQUENCE = VP3_SURFACE_DOMAIN if use_surface_domain else VP3_FULL
    target_label = "surface" if use_surface_domain else "full"

    worker_id = str(uuid.uuid4())[:8]
    print(f"\n{'='*60}")
    print(f"  WORKER {worker_id} STARTED")
    print(f"  Binder length: {binder_length} AA")
    print(f"  Target: VP3 {target_label} ({len(TARGET_SEQUENCE)} AA)")
    print(f"  Time budget: {max_runtime_seconds/3600:.1f} hours")
    print(f"{'='*60}\n")

    # Load models
    print(f"[{worker_id}] Loading Boltz-2 model...")
    folder = Boltz2()
    print(f"[{worker_id}] Loading ProteinMPNN...")
    mpnn = load_mpnn_sol(0.05)
    print(f"[{worker_id}] Models loaded. Starting design loop.\n")

    # Block cysteine residues
    bias = jnp.zeros((binder_length, 20)).at[:binder_length, TOKENS.index("C")].set(-1e6)

    # ---- LOSS FUNCTION ----
    sp_loss = (
        sp.BinderTargetContact()
        + sp.WithinBinderContact()
        + 10.0 * InverseFoldingSequenceRecovery(mpnn, temp=jnp.array(0.001), bias=bias)
        + 0.05 * sp.TargetBinderPAE()
        + 0.05 * sp.BinderTargetPAE()
        + 0.025 * sp.IPTMLoss()
        + 0.4 * sp.WithinBinderPAE()
        + 0.025 * sp.pTMEnergy()
        + 0.1 * sp.PLDDTLoss()
    )

    features, _ = folder.binder_features(
        binder_length=binder_length,
        chains=[TargetChain(sequence=TARGET_SEQUENCE, use_msa=True)],
    )

    loss = NoCys(
        folder.build_multisample_loss(
            loss=sp_loss,
            features=features,
            recycling_steps=1,
            num_samples=4,
        )
    )

    @eqx.filter_jit
    def evaluate_loss(loss, pssm, key):
        return loss(pssm, key=key)

    def design_one():
        """Generate a single binder design via 3-stage gradient optimization."""
        _pssm = np.random.uniform(low=0.25, high=0.75) * jax.random.gumbel(
            key=jax.random.key(np.random.randint(10000000)),
            shape=(binder_length, 19)
        )

        # Stage 1: Soft optimization (100 steps)
        _, pssm = simplex_APGM(
            loss_function=loss, x=jax.nn.softmax(_pssm),
            n_steps=100, stepsize=0.2 * np.sqrt(binder_length),
            momentum=0.3, scale=1.00, logspace=False, max_gradient_norm=1.0,
        )
        # Stage 2: Sharpening (50 steps)
        pssm, _ = simplex_APGM(
            loss_function=loss, x=jnp.log(pssm + 1e-5),
            n_steps=50, stepsize=0.5 * np.sqrt(binder_length),
            momentum=0.0, scale=1.25, logspace=True, max_gradient_norm=1.0,
        )
        # Stage 3: Final hardening (15 steps)
        pssm, _ = simplex_APGM(
            loss_function=loss, x=jnp.log(pssm + 1e-5),
            n_steps=15, stepsize=0.5 * np.sqrt(binder_length),
            momentum=0.0, scale=1.4, logspace=True, max_gradient_norm=1.0,
        )

        # Convert to discrete sequence
        pssm = NoCys.sequence(pssm)
        seq = pssm.argmax(-1)
        seq_str = "".join(TOKENS[i] for i in seq)

        # ---- RANKING (Boltz-2 cross-validation) ----
        boltz_features, _ = folder.target_only_features(
            chains=[
                TargetChain(sequence=seq_str, use_msa=False),
                TargetChain(sequence=TARGET_SEQUENCE, use_msa=True),
            ]
        )
        ranking_loss = folder.build_multisample_loss(
            loss=(
                1.00 * sp.IPTMLoss()
                + 0.5 * sp.TargetBinderIPSAE()
                + 0.5 * sp.BinderTargetIPSAE()
            ),
            features=boltz_features, recycling_steps=3, num_samples=6,
        )
        loss_value, _ = evaluate_loss(
            ranking_loss, jax.nn.one_hot(seq, 20), key=jax.random.key(0)
        )
        return (seq_str, loss_value.item())

    # ---- DESIGN LOOP WITH CHECKPOINTS ----
    outfile = f"/structures/designs_len{binder_length}_{target_label}_{worker_id}.txt"
    checkpoint_file = f"/structures/checkpoint_{worker_id}.txt"
    start_time = time.time()
    results = []
    design_count = 0
    best_loss = float("inf")

    while time.time() - start_time < max_runtime_seconds:
        iter_start = time.time()
        seq, loss_value = design_one()
        iter_time = time.time() - iter_start
        design_count += 1
        elapsed = time.time() - start_time
        remaining = max_runtime_seconds - elapsed

        if loss_value < best_loss:
            best_loss = loss_value
            is_best = " *** NEW BEST ***"
        else:
            is_best = ""

        # ---- CHECKPOINT LOG ----
        print(f"\n{'─'*60}")
        print(f"  CHECKPOINT — Worker {worker_id} — Design #{design_count}")
        print(f"  Loss: {loss_value:.4f}{is_best}")
        print(f"  Best so far: {best_loss:.4f}")
        print(f"  This design took: {iter_time/60:.1f} min")
        print(f"  Elapsed: {elapsed/60:.1f} min | Remaining: {remaining/60:.1f} min")
        print(f"  Estimated designs left: ~{int(remaining / iter_time) if iter_time > 0 else '?'}")
        print(f"  Sequence: {seq[:40]}...")
        print(f"{'─'*60}\n")

        # Write design to volume
        with open(outfile, "a") as f:
            f.write(f">{loss_value:.4f}\n{seq}\n")

        # Write checkpoint summary (overwritten each time)
        with open(checkpoint_file, "w") as f:
            f.write(f"worker={worker_id}\n")
            f.write(f"designs_completed={design_count}\n")
            f.write(f"best_loss={best_loss:.4f}\n")
            f.write(f"latest_loss={loss_value:.4f}\n")
            f.write(f"elapsed_min={elapsed/60:.1f}\n")
            f.write(f"remaining_min={remaining/60:.1f}\n")
            f.write(f"avg_min_per_design={elapsed/60/design_count:.1f}\n")

        results.append((seq, loss_value))
        vol.commit()

    # ---- FINAL SUMMARY ----
    results.sort(key=lambda x: x[1])
    print(f"\n{'='*60}")
    print(f"  WORKER {worker_id} FINISHED")
    print(f"  Total designs: {design_count}")
    print(f"  Total time: {(time.time()-start_time)/60:.1f} min")
    print(f"  Best loss: {results[0][1]:.4f}")
    print(f"  Top 5 losses: {[f'{r[1]:.4f}' for r in results[:5]]}")
    print(f"{'='*60}\n")

    return results


# ============================================================================
# STAGE 2: PROTENIX CROSS-VALIDATION
# ============================================================================
@app.function(
    image=protenix_image,
    gpu="A100-80GB",
    timeout=int(12 * 60 * 60),
    volumes={"/structures": vol},
)
def score_protenix(
    sequences: list[str],
    target_sequence: str = VP3_SURFACE_DOMAIN,
):
    """
    Score binder-target complexes with Protenix (AF3-equivalent).
    Returns ipTM, pTM, and ranking scores for each design.
    """
    import json
    import os
    import subprocess
    import glob
    import time

    # Download model weights on first run (needs GPU/CUDA available)
    print("Downloading Protenix model weights (first run only)...")
    subprocess.run(
        ["protenix", "download", "--model", "protenix_base_20250630_v1.0.0"],
        check=True, capture_output=True,
    )
    print("Model weights ready.")

    total = len(sequences)
    results = []
    work_dir = "/tmp/protenix_scoring"
    os.makedirs(work_dir, exist_ok=True)
    start_time = time.time()

    # Checkpoint file on shared volume — survives crashes/timeouts
    protenix_checkpoint = "/structures/protenix_scores_checkpoint.json"

    print(f"\n{'='*60}")
    print(f"  PROTENIX SCORING — {total} designs to validate")
    print(f"  Checkpointing to volume after every design")
    print(f"{'='*60}\n")

    for idx, binder_seq in enumerate(sequences):
        iter_start = time.time()
        print(f"[Protenix {idx+1}/{total}] Scoring: {binder_seq[:30]}...")

        input_json = {
            "name": f"5mv5_vp3_binder_{idx:04d}",
            "sequences": [
                {"protein": {"id": "A", "sequence": binder_seq}},
                {"protein": {"id": "B", "sequence": target_sequence}},
            ],
            "modelSeeds": [42, 43, 44],
        }

        input_path = os.path.join(work_dir, f"input_{idx:04d}.json")
        output_dir = os.path.join(work_dir, f"output_{idx:04d}")
        os.makedirs(output_dir, exist_ok=True)

        with open(input_path, "w") as f:
            json.dump([input_json], f, indent=2)

        try:
            cmd = [
                "protenix", "pred",
                "-i", input_path,
                "-o", output_dir,
                "-n", "protenix_base_20250630_v1.0.0",
                "--seeds", "42,43,44",
                "--use_msa", "false",
            ]
            subprocess.run(cmd, check=True, capture_output=True, timeout=600)

            summary_files = glob.glob(
                os.path.join(output_dir, "**", "*summary*.json"), recursive=True
            )
            if not summary_files:
                summary_files = glob.glob(
                    os.path.join(output_dir, "**", "*.json"), recursive=True
                )

            best_score = None
            best_iptm = None
            best_ptm = None

            for sf in summary_files:
                try:
                    with open(sf) as f2:
                        data = json.load(f2)
                    if isinstance(data, dict):
                        score = data.get("ranking_score", data.get("ranking_confidence", None))
                        iptm = data.get("iptm", data.get("interface_ptm", None))
                        ptm = data.get("ptm", data.get("predicted_tm_score", None))
                        if score is not None and (best_score is None or score > best_score):
                            best_score = score
                            best_iptm = iptm
                            best_ptm = ptm
                except (json.JSONDecodeError, KeyError):
                    continue

            iter_time = time.time() - iter_start
            elapsed = time.time() - start_time
            remaining_est = (elapsed / (idx + 1)) * (total - idx - 1)

            print(f"  -> ranking_score={best_score}, ipTM={best_iptm}, ptm={best_ptm}")
            print(f"     took {iter_time/60:.1f}min | "
                  f"progress {idx+1}/{total} | "
                  f"~{remaining_est/60:.0f}min remaining")

            results.append({
                "index": idx,
                "sequence": binder_seq,
                "protenix_ranking_score": best_score,
                "protenix_iptm": best_iptm,
                "protenix_ptm": best_ptm,
                "status": "success" if best_score is not None else "no_score_found",
            })

        except subprocess.TimeoutExpired:
            results.append({"index": idx, "sequence": binder_seq, "status": "timeout"})
            print(f"  -> TIMEOUT")
        except subprocess.CalledProcessError as e:
            err = e.stderr[:200] if e.stderr else "unknown"
            results.append({"index": idx, "sequence": binder_seq, "status": f"error: {err}"})
            print(f"  -> ERROR: {err[:100]}")

        # Checkpoint scores to volume after every design
        with open(protenix_checkpoint, "w") as f:
            json.dump(results, f, indent=2)
        vol.commit()
        print(f"     [checkpoint saved — {len(results)}/{total} scored on volume]")

    print(f"\n{'='*60}")
    print(f"  PROTENIX COMPLETE — {len(results)} scored in {(time.time()-start_time)/60:.1f}min")
    print(f"{'='*60}\n")

    return results


# ============================================================================
# ENTRYPOINT
# ============================================================================
@app.local_entrypoint()
def main(
    # Design parameters
    max_time_hours: float = 3.0,
    binder_lengths: str = "55,70,80",  # one worker per length
    use_surface_domain: bool = True,
    # Output
    output_path: str = "",
    # Scoring
    run_protenix: bool = True,
    score_only: bool = False,
    input_fasta: str = "",
    top_n_to_score: int = 100,
):
    """
    5MV5 VP3 Binder Design Pipeline.

    Target: Chain C (VP3) surface domain of Deformed Wing Virus (PDB 5MV5)
    Default: 5 workers (lengths 55,70,80,90,100) x 3 hours, then Protenix validates top 100.

    Examples:
      # Default: one worker per length + Protenix scoring
      uvx modal run 5mv5_chainC_design.py

      # Custom lengths
      uvx modal run 5mv5_chainC_design.py --binder-lengths "60,80,120"

      # Score existing designs with Protenix only
      uvx modal run 5mv5_chainC_design.py --score-only --input-fasta designs.txt
    """
    import json

    lengths = [int(x.strip()) for x in binder_lengths.split(",")]

    if not output_path:
        target_label = "surface" if use_surface_domain else "full"
        output_path = f"5mv5_vp3_designs_mixed_{target_label}.txt"

    # ---- SCORE-ONLY MODE ----
    if score_only:
        if not input_fasta:
            print("ERROR: --input-fasta required with --score-only")
            return

        sequences = []
        boltz_scores = []
        with open(input_fasta) as f:
            for line in f:
                line = line.strip()
                if line.startswith(">"):
                    parts = line[1:].split("_")
                    score = float(parts[-1]) if len(parts) > 1 else 0.0
                    boltz_scores.append(score)
                elif line:
                    sequences.append(line)

        sorted_indices = sorted(range(len(boltz_scores)), key=lambda i: boltz_scores[i])
        top_seqs = [sequences[i] for i in sorted_indices[:top_n_to_score]]
        print(f"Scoring top {len(top_seqs)} designs with Protenix...")

        target = VP3_SURFACE_DOMAIN if use_surface_domain else VP3_FULL
        px_results = score_protenix.remote(top_seqs, target)

        results_path = output_path.replace(".txt", "_scored.json")
        combined = []
        for i, px in enumerate(px_results):
            orig_idx = sorted_indices[i]
            combined.append({
                "rank": i + 1,
                "sequence": px["sequence"],
                "boltz2_loss": boltz_scores[orig_idx],
                "protenix_iptm": px.get("protenix_iptm"),
                "protenix_ranking_score": px.get("protenix_ranking_score"),
                "protenix_status": px.get("status"),
            })

        with open(results_path, "w") as f:
            json.dump(combined, f, indent=2)
        print(f"Results written to {results_path}")
        return

    # ---- DESIGN MODE ----
    target_seq = VP3_SURFACE_DOMAIN if use_surface_domain else VP3_FULL
    print(f"\n{'='*60}")
    print(f"  5MV5 VP3 BINDER DESIGN CAMPAIGN")
    print(f"{'='*60}")
    print(f"  Target: PDB 5MV5 Chain C (VP3, Deformed Wing Virus)")
    print(f"  Region: {'surface domain' if use_surface_domain else 'full VP3'} "
          f"({len(target_seq)} AA)")
    print(f"  Binder lengths: {lengths} (one worker each)")
    print(f"  Workers: {len(lengths)} (parallel A100-80GB)")
    print(f"  Time per worker: {max_time_hours} hours")
    print(f"  Expected designs: ~{len(lengths) * 20} (est. ~20/worker)")
    print(f"  Protenix validation: top {top_n_to_score}")
    print(f"  Output: {output_path}")
    print(f"{'='*60}\n")

    # Launch one worker per binder length in parallel
    # NOTE: Even if this entrypoint crashes, every design is safely saved
    # on the Modal volume in per-worker files (designs_len*_surface_*.txt).
    # Recover with: python3 -m modal volume get 5mv5-vp3-binders .
    arguments = [
        (int(max_time_hours * 60 * 60), length, use_surface_domain)
        for length in lengths
    ]
    all_results = []
    for result_batch in design_boltz2.starmap(arguments):
        all_results.extend(result_batch)

    # Sort by Boltz-2 ranking loss (lower = better)
    all_results.sort(key=lambda x: x[1])

    # Write FASTA locally (include length in header for tracking)
    with open(output_path, "w") as f:
        for idx, (seq, loss_value) in enumerate(all_results):
            f.write(f">design{idx}_len{len(seq)}_{loss_value:.4f}\n{seq}\n")

    print(f"\n{'='*60}")
    print(f"  STAGE 1 COMPLETE — BOLTZ-2 DESIGN")
    print(f"{'='*60}")
    print(f"  Generated {len(all_results)} designs")
    print(f"  Best Boltz-2 loss: {all_results[0][1]:.4f}")
    print(f"  Top 10 losses: {[f'{r[1]:.4f}' for r in all_results[:10]]}")
    print(f"  Written to: {output_path}")
    print(f"{'='*60}\n")

    # ---- PROTENIX CROSS-VALIDATION ----
    if run_protenix and all_results:
        n_to_score = min(top_n_to_score, len(all_results))
        top_seqs = [seq for seq, _ in all_results[:n_to_score]]

        print(f"\n{'='*60}")
        print(f"  STAGE 2 — PROTENIX CROSS-VALIDATION")
        print(f"  Scoring top {n_to_score} Boltz-2 designs")
        print(f"{'='*60}\n")

        target = VP3_SURFACE_DOMAIN if use_surface_domain else VP3_FULL
        px_results = score_protenix.remote(top_seqs, target)

        results_path = output_path.replace(".txt", "_consensus.json")
        combined = []
        for i, px in enumerate(px_results):
            combined.append({
                "rank": i + 1,
                "sequence": px["sequence"],
                "boltz2_loss": all_results[i][1],
                "protenix_iptm": px.get("protenix_iptm"),
                "protenix_ranking_score": px.get("protenix_ranking_score"),
                "protenix_ptm": px.get("protenix_ptm"),
                "protenix_status": px.get("status"),
            })

        with open(results_path, "w") as f:
            json.dump(combined, f, indent=2)

        # ---- FINAL REPORT ----
        print(f"\n{'='*60}")
        print(f"  FINAL RESULTS — CONSENSUS RANKING")
        print(f"{'='*60}")
        print(f"  Results: {results_path}\n")
        print(f"  {'Rank':<6} {'Boltz2':<10} {'PX ipTM':<10} {'PX Score':<10} {'Sequence'}")
        print(f"  {'─'*6} {'─'*10} {'─'*10} {'─'*10} {'─'*30}")
        for entry in combined[:20]:
            px_iptm = entry.get("protenix_iptm", "N/A")
            px_score = entry.get("protenix_ranking_score", "N/A")
            if isinstance(px_iptm, float):
                px_iptm = f"{px_iptm:.3f}"
            if isinstance(px_score, float):
                px_score = f"{px_score:.3f}"
            print(f"  #{entry['rank']:<5} {entry['boltz2_loss']:<10.4f} "
                  f"{px_iptm:<10} {px_score:<10} {entry['sequence'][:30]}...")
        print(f"{'='*60}")
