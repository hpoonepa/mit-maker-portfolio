# Paper Crane — Protein Dynamics POC

**September 28 update:** the current Ember implementation is in
[`ember/`](ember/README.md). The pipeline below is the historical proof of concept;
its documented mapping, pocket-parser and trajectory assumptions have not been
used for the new benchmark. Use Ember's separate evaluator and execution plan for
new work. Ember training and predictive benchmarking remain pending.

Greenfield pipeline: BioEmu (ensemble) → fpocket (pocket detection) → cluster →
cryptic-pocket calls, benchmarked on the PocketMiner apo/holo dataset.

This directory is parallel to `src/`, `vast/`, `validators/`.

## Running tests

Always run pytest from the mosaic project root so that the `dynamics` package is importable:

```bash
cd /Users/harsha/Desktop/claudeprojects/mosaic
pytest dynamics/tests -v
```

## Tool versions

- **fpocket**: NOT INSTALLED LOCALLY on this macOS workstation.
  - `which fpocket` returns nothing; `brew info fpocket` returns `Error: No available
    formula with the name "fpocket"` (no Homebrew formula exists at this date).
  - System-wide installation was outside the local setup scope (no sudo, no admin).
  - Plan: fpocket is Linux-native; it will run inside the Docker image / on the Vast.ai
    worker (Task 10 + Task 11). Local dev can mock fpocket output via fixtures, or
    install from source via `git clone https://github.com/Discngine/fpocket && make`
    on the controller's choice.

- **BioEmu**: commit `135031611c2acf11b293ff58dfd91fa97592ebd2` (microsoft/bioemu,
  `main` branch, shallow clone at `/tmp/bioemu` on 2026-05-20).
  - Pip package: `pip install bioemu` (Linux-only). Add `[cuda]` extra for GPU support.
  - Python 3.10+. AlphaFold2 weights (~3.5 GB) auto-downloaded to
    `~/.cache/colabfold/` on first run.

## BioEmu CLI

Exact invocation form (from `README.md` and `src/bioemu/sample.py:70`):

```bash
python -m bioemu.sample \
    --sequence <AA_STRING_or_path_to.fasta_or_.a3m> \
    --num_samples <N> \
    --output_dir <dir> \
    [--model_name bioemu-v1.1] \
    [--batch_size_100 10] \
    [--filter_samples True] \
    [--base_seed <int>] \
    [--denoiser_config src/bioemu/config/steering/physical_steering.yaml]
```

**Inputs accepted by `--sequence`**:
- Raw amino-acid string (e.g. `GYDPETGTWG`)
- Path to a single-sequence FASTA file
- Path to an `.a3m` MSA file (query sequence first row); skips ColabFold MMseqs2

> Note: BioEmu takes **sequence input**. To benchmark against a
> PocketMiner apo PDB, we must first extract the sequence from the PDB (Biopython
> `SeqIO`) and feed that into `bioemu.sample`. The "topology" output PDB then carries
> coordinates that can be aligned back to the experimental apo structure.

**Outputs** in `--output_dir` (from `src/bioemu/sample.py:226-227`):
- `topology.pdb` — single reference structure (one frame, all atoms used in xtc)
- `samples.xtc` — MD-style trajectory file with N frames (one per generated sample)
- `sequence.fasta` — the input sequence (saved for reproducibility)
- intermediate `.npz` batch files (deleted after conversion to xtc/pdb)

> Important: BioEmu outputs **backbone-only frames**. To get all-atom PDB files (one
> per frame) suitable for fpocket, we must run side-chain reconstruction:
> ```bash
> python -m bioemu.sidechain_relax --pdb-path topology.pdb --xtc-path samples.xtc
> ```
> This produces `samples_sidechain_rec.{pdb,xtc}` and optionally `samples_md_equil.{pdb,xtc}`
> (with `--md-protocol nvt_equil`). Side-chain reconstruction uses HPacker and
> **requires conda + CUDA12**.

**GPU / VRAM requirements** (from README sampling table):

| sequence length | time per 1000 samples on A100-80GB |
|----------------:|-----------------------------------:|
| 100             | 4 min                              |
| 300             | 40 min                             |
| 600             | 150 min                            |

`batch_size_100=20` for the table above. Default is 10. A100-80GB is the reference
GPU; smaller VRAM (e.g. 40 GB) will require reducing `batch_size_100`. A hard minimum VRAM remains unspecified in the README.

**Sampler / multimer caveats**:
- Monomers only. Multimer "linker trick" is mentioned but not recommended.
- Default sampler is DPM (`--denoiser_type dpm`); Heun also supported.
- For physical steering: `--denoiser_config src/bioemu/config/steering/physical_steering.yaml`.

## PocketMiner benchmark

**Source**: cloned from `Mickdub/gvp` (no `pocket_pred` branch needed — the data
sits on both branches at the same path; we used the `pocket_pred` branch, commit
`187062df3c94127e991669768009141a08fd5d8b`).

**Path to apo/holo table**:
```
/tmp/gvp/data/pm-dataset/supplementary-tables.xlsx
```
After cloning to the worker, in-repo path is:
```
data/pm-dataset/supplementary-tables.xlsx
```

**Sheet**: `validation_and_test_sets` — this is the primary apo/holo benchmark.
Two other relevant sheets:
- `training_5fcv` — 37 training pairs (CryptoSite-derived, 5-fold CV)
- `highly_rigid_proteins` — 8 negative controls (no pocket opening expected)
- `MOAD negatives` — 10 additional negative-control proteins from MOAD

**Header structure of `validation_and_test_sets`** (3 header rows merged; row 3
contains the actual column names). Column index → name (0-indexed; column 0 is blank):

| idx | column name |
|----:|-------------|
| 1   | (section label: "Novel cryptic pocket set" / "Cryptosite proteins ..." / "Highly rigid proteins ...") |
| 2   | apo PDB ID |
| 4   | apo chain ID |
| 5   | apo number of resolved residues |
| 6   | holo PDB ID |
| 7   | holo chain ID |
| 8   | holo ligand code |
| 9   | holo number of resolved residues |
| 10  | number of resolved cryptic ligand-lining residues |
| 11  | CATH code |
| 12  | motion type (prioritized: lr > ssc > id > ssm > loop) |
| 13  | dominant motion |
| 14  | mean cryptic-residue distance, apo (nm) |
| 15  | mean cryptic-residue distance, holo (nm) |
| 16  | pocket direction (apo-holo distance based) |
| 17  | pocket direction (manually assigned) |
| 18  | apo-holo all-Cα RMSD (nm) |
| 19  | ligand-lining residue all-heavy-atom RMSD (nm) |
| 20  | structure source / filtering criterion |
| 21  | set ("validation" or "test") |
| 22  | notes |

**Row counts** (data rows with a 4-character apo PDB ID in col 2):
- Total: **49**
  - `set == "validation"`: **21**
  - `set == "test"`: **28**
- Section breakdown:
  - "Novel cryptic pocket set"
  - "Cryptosite proteins used in validation..."
  - "Highly rigid proteins; see eponymous tab for details" (negative controls,
    holo columns marked `n/a`)

Total xlsx rows including all 3 header rows = 52.

**Supporting files in `data/pm-dataset/`**:
- `apo-structures/` — cleaned apo PDBs (missing loops modeled) — direct inputs for
  the model
- `all-structures/` — all apo + holo PDBs (with ligands for holo)
- `test_apo_ids_with_chainids.npy`, `val_apo_ids_with_chainids.npy` — per-set apo
  IDs with chain suffixes (the form `1ADEA` = PDB 1ADE chain A)
- `test_label_dictionary.npy`, `val_label_dictionary.npy` — per-residue cryptic
  pocket labels for evaluation

Task 6 (`datasets.py`) will parse this xlsx into a clean CSV of `(apo_pdb,
apo_chain, holo_pdb, holo_chain, ligand_code, set, motion_type)` tuples, restricted
to rows where holo is not `n/a` (i.e. excluding pure rigid-protein negatives).

## Docker build status

**Task 10 — Dockerfile authored, NOT built locally.**

`docker` is **not installed** on the local macOS workstation (`which docker` returns
nothing, `docker --version` exits with `docker not found`). Docker installation requires an admin-level system change outside this setup
scope. The image awaits build and smoke testing on the worker.

The Dockerfile (`dynamics/Dockerfile`) and `.dockerignore` are committed and ready
to build on the Vast.ai worker (Task 12) or on any Linux host with Docker. To build:

```bash
cd /Users/harsha/Desktop/claudeprojects/mosaic
docker build -f dynamics/Dockerfile -t papercrane/dynamics:dev .
# smoke-test argparse banner:
docker run --rm papercrane/dynamics:dev --help
```

**Image design notes** (cross-checked against `/tmp/bioemu/README.md` and `pyproject.toml`):

| Concern | Source / Resolution |
|---------|---------------------|
| CUDA base | `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04` (BioEmu mandates CUDA12 for `sidechain_relax`). |
| Conda required? | BioEmu README warns conda + CUDA12 drivers must be present for `sidechain_relax`. Bundled `hpacker_setup/setup_sidechain_relax.sh` actually uses a plain `python3 -m venv` (no `conda env create`), but we ship miniconda anyway since the README is the contract. |
| BioEmu install | `pip install "bioemu[cuda,md] @ git+https://github.com/microsoft/bioemu.git@<pinned-commit>"`. `[cuda]` pulls `jax[cuda12]==0.4.35 + nvidia-cuda-nvcc-cu12==12.8.93`; `[md]` pulls `openmm==8.4.0 + openmm-cuda-12==8.4.0`. Commit pinned for reproducibility. |
| HPacker install | NOT pre-baked. BioEmu's `sidechain_relax` first-run trigger clones `gvisani/hpacker`, creates `~/.hpacker_venv`, installs PyTorch CU118 + deps, installs hpacker. `git` + `python3-venv` are present in the image; first sidechain call inside a container pays this one-time cost (~3 GB pip downloads). |
| fpocket | `apt-get install fpocket` from Ubuntu 22.04 universe (enabled via `software-properties-common` + `add-apt-repository universe`). |
| Project deps | `dynamics/requirements.txt` (biopython, numpy, pandas, scipy, openpyxl, requests, pytest, pytest-mock). |
| Entrypoint | `python -m dynamics.run_target` (per-target CLI from Task 8). |
| Image size estimate | CUDA runtime ~3.5 GB + conda ~500 MB + bioemu+jax+torch+openmm ~4–5 GB + apt deps + project ~200 MB ≈ **8–10 GB**. HPacker venv adds ~3 GB at first runtime. |

**Concerns / open risks** (to validate on Task 12 build):

1. `bioemu[cuda,md]` combo isn't tested by us — possible jax/torch version conflict (jax 0.4.35 ↔ torch from `[md]` indirect). If the wheel resolver complains, split into two `pip install` calls (cuda first, then md) or drop `[md]` and rely on hpacker_setup's own torch install.
2. `nvidia-cuda-nvcc-cu12==12.8.93` in `[cuda]` mismatches the base image's CUDA 12.4 runtime. JAX uses its own bundled CUDA libs so this is typically fine, but worth a `python -c "import jax; jax.devices()"` smoke test on the worker.
3. fpocket version in Ubuntu 22.04 universe is v3.1.4.2 (verified per Debian package tracker). If a newer version is required, swap the apt line for `git clone https://github.com/Discngine/fpocket && cd fpocket && make`.
4. `--help` smoke test not run — argparse banner from `run_target.py` is unverified inside the image. Local pytest (`pytest dynamics/tests -v`) covers the CLI logic, but containerized PATH + entrypoint can only be validated post-build.

## Cost Log

| Date | Item | Provider | $ | Notes |
|------|------|----------|---|-------|
|      |      |          |   |       |
