"""Modal script for running JAX + CUDA GPU workloads remotely.

Designed for mosaic protein design workflows (Protenix2025, ProteinMPNN).
Adapt the image setup, function body, and local_entrypoint to your needs.

Usage:
    modal run modal_run.py              # run once
    modal run modal_run.py --timeout 30 # with CLI args
    modal deploy modal_run.py           # persistent deployment

Requirements:
    pip install modal
    modal token new  # one-time auth setup"""

import modal
import os

# ---------------------------------------------------------------------------
# 1. Volume -- persistent cache for model weights between runs
# ---------------------------------------------------------------------------
# Create once: `modal volume create mosaic-weights`
# Or let create_if_missing handle it automatically.
weights_vol = modal.Volume.from_name("mosaic-weights", create_if_missing=True)

# ---------------------------------------------------------------------------
# 2. Image -- container environment with GPU, JAX, and project dependencies
# ---------------------------------------------------------------------------
# Modal host provides: NVIDIA driver 580.95.05, CUDA driver API 13.0.
# JAX's cuda13 pip extra bundles cuDNN/NCCL user-mode libs automatically.

image = (
    # Start from a slim Debian base (matches your local Python version).
    modal.Image.debian_slim(python_version="3.12")

    # System packages needed for builds and downloads.
    .apt_install("curl", "git", "wget", "build-essential")

    # JAX with CUDA 13 support (the recommended GPU variant as of 2025).
    # Pin versions tightly for reproducibility.
    .uv_pip_install(
        "jax[cuda13]",
        "jaxlib",
        "numpy",
        "scipy",
    )

    # Install a Python package from a git repo using uv.
    # NOTE: mosaic has a dep conflict (scipy==1.15.1 vs protenix>=1.15.3).
    # Commented out until upstream fixes it. Current workload doesn't need it.
    # .uv_pip_install(
    #     "git+https://github.com/escalante-bio/mosaic.git",
    # )
    # For PRIVATE repos, use pip_install_private_repos instead:
    # .pip_install_private_repos(
    #     "github.com/escalante-bio/mosaic",
    #     secret=modal.Secret.from_name("github-token"),
    #     # Requires a Modal secret with GITHUB_TOKEN that has repo read access.
    # )

    # Alternative: install from a local checkout (if you prefer).
    # .add_local_dir(".", remote_path="/root/mosaic", copy=True)
    # .run_commands("cd /root/mosaic && pip install -e .")

    # Download a file from the internet during image build (curl).
    # This gets baked into the image layer and cached.
    .run_commands(
        "curl -fsSL -o /root/5G51.cif https://files.rcsb.org/download/5G51.cif",
    )

    # Set environment variables for JAX/XLA on GPU.
    .env({
        # Pre-allocate 90% of GPU memory to avoid fragmentation.
        "XLA_PYTHON_CLIENT_MEM_FRACTION": "0.9",
        # Optionally pin to a single GPU (useful for debugging).
        # "CUDA_VISIBLE_DEVICES": "0",
        # Disable JAX persistent compilation cache if it causes issues.
        # "JAX_ENABLE_COMPILATION_CACHE": "0",
    })
)

# ---------------------------------------------------------------------------
# 3. App definition
# ---------------------------------------------------------------------------
app = modal.App(name="mosaic-jax-gpu", image=image)

# ---------------------------------------------------------------------------
# 4. Remote GPU function
# ---------------------------------------------------------------------------
@app.function(
    gpu="A100-80GB",          # GPU type. Options: "A100", "A100-40GB", "A100-80GB",
                               # "H100", "H100!" (no auto-upgrade to H200), "H200",
                               # "L4", "T4", "A10G", "L40S".
                               # Multi-GPU: "H100:8" for 8x H100.
    timeout=3600,              # Max wall-clock seconds (1 hour).
    volumes={"/weights": weights_vol},  # Mount the persistent volume.
    # min_containers=0,       # Keep-warm containers (costs $ when idle).
    # max_containers=1,       # Cap autoscaling.
    # scaledown_window=300,   # Seconds idle before container shutdown.
)
def run_jax_workload(target_cif_path: str = "/root/5G51.cif") -> dict:
    """
    Run a JAX + CUDA workload on a remote GPU.

    Returns a dict with output file bytes and metadata so the local
    entrypoint can save them to disk.
    """
    import jax
    import jax.numpy as jnp

    # -----------------------------------------------------------------------
    # Verify GPU is available
    # -----------------------------------------------------------------------
    devices = jax.devices()
    print(f"JAX devices: {devices}")
    print(f"JAX default backend: {jax.default_backend()}")
    assert jax.default_backend() == "gpu", "Expected GPU backend!"
    print(f"GPU: {devices[0].device_kind}")

    # -----------------------------------------------------------------------
    # Use the persistent volume to cache model weights
    # -----------------------------------------------------------------------
    import os
    weights_dir = "/weights/protenix2025"
    if os.path.exists(weights_dir) and os.listdir(weights_dir):
        print(f"Model weights found in volume cache: {weights_dir}")
    else:
        print("Downloading model weights (first run only)...")
        os.makedirs(weights_dir, exist_ok=True)
        # === Replace with your actual weight download logic ===
        # Example: huggingface_hub.snapshot_download(repo_id="...", local_dir=weights_dir)
        # After download, commit the volume so future runs skip this step.
        weights_vol.commit()
        print("Weights cached in volume for future runs.")

    # -----------------------------------------------------------------------
    # Your JAX + CUDA workload goes here
    # -----------------------------------------------------------------------
    # Example: a simple JAX computation to prove GPU works.
    # Replace this with your actual mosaic/Protenix2025 workflow.
    key = jax.random.PRNGKey(42)
    x = jax.random.normal(key, (4096, 4096))
    y = jnp.dot(x, x.T)  # GPU matmul
    result_norm = float(jnp.linalg.norm(y))
    print(f"Computed matrix norm on GPU: {result_norm:.4f}")

    # -----------------------------------------------------------------------
    # Example: read the downloaded CIF file
    # -----------------------------------------------------------------------
    with open(target_cif_path, "r") as f:
        cif_lines = len(f.readlines())
    print(f"Target CIF file has {cif_lines} lines")

    # -----------------------------------------------------------------------
    # Produce output files
    # -----------------------------------------------------------------------
    # Option A: Return file bytes directly (good for small-to-medium files).
    # The local_entrypoint receives these and writes to disk.
    output_pdb = f"REMARK  Generated by mosaic on Modal\nRMARK  norm={result_norm}\nEND\n"
    output_log = f"devices: {devices}\nnorm: {result_norm}\ncif_lines: {cif_lines}\n"

    # Option B: Write large files to the Volume, download later via CLI.
    # with open("/weights/outputs/complex.pdb", "w") as f:
    #     f.write(output_pdb)
    # weights_vol.commit()  # persist to volume

    return {
        "complex.pdb": output_pdb.encode(),
        "run_log.txt": output_log.encode(),
        "norm": result_norm,
    }


# ---------------------------------------------------------------------------
# 5. Local entrypoint -- runs on YOUR machine, orchestrates remote calls
# ---------------------------------------------------------------------------
@app.local_entrypoint()
def main(
    output_dir: str = "./modal_outputs",
    timeout: int = 3600,
):
    """
    Entry point that runs locally. Calls the remote GPU function,
    receives results, and saves output files to your local machine.

    Usage:
        modal run modal_run.py
        modal run modal_run.py --output-dir ./my_outputs
    """
    import pathlib

    print(f"Launching JAX workload on remote A100-80GB GPU...")
    result = run_jax_workload.remote()

    # Save returned files locally.
    out = pathlib.Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    for filename, content in result.items():
        if isinstance(content, bytes):
            filepath = out / filename
            filepath.write_bytes(content)
            print(f"Saved: {filepath}")

    print(f"\nGPU matmul norm: {result['norm']}")
    print("Done.")


# ---------------------------------------------------------------------------
# 6. Alternative: Volume-based output retrieval
# ---------------------------------------------------------------------------
# If your outputs are large (GB-scale), write them to the Volume inside
# the GPU function, then download locally with the Modal CLI:
#
#   modal volume get mosaic-weights /outputs/complex.pdb ./complex.pdb
#   modal volume ls mosaic-weights /outputs/
#
# Or read programmatically:
#
#   vol = modal.Volume.from_name("mosaic-weights")
#   data = vol.read_file("/outputs/complex.pdb")
#   pathlib.Path("complex.pdb").write_bytes(data)


# ---------------------------------------------------------------------------
# APPENDIX: Common patterns reference
# ---------------------------------------------------------------------------
#
# GPU FALLBACKS -- try A100 first, fall back to cheaper options:
#   @app.function(gpu=["A100-80GB", "A100-40GB", "H100", "L40S"])
#
# MULTI-GPU -- for large models or data parallelism:
#   @app.function(gpu="H100:8")
#
# CONCURRENT REQUESTS -- serve multiple inputs per container:
#   @modal.concurrent(max_inputs=5)
#   @app.function(gpu="A100")
#   def serve(input): ...
#
# CLASS-BASED with lifecycle hooks -- load model once, serve many:
#   @app.cls(gpu="A100-80GB", volumes={"/weights": weights_vol})
#   class Model:
#       @modal.enter()
#       def load(self):
#           self.model = load_model("/weights/...")
#
#       @modal.method()
#       def predict(self, x):
#           return self.model(x)
#
#       @modal.exit()
#       def cleanup(self):
#           save_metrics()
#
# INSTALL FROM LOCAL SOURCE (Modal 1.0+ pattern, replaces Mount):
#   image = modal.Image.debian_slim().add_local_python_source("my_module")
#   @app.function(image=image)
#   def f(): import my_module
#
# FORCE IMAGE REBUILD:
#   MODAL_FORCE_BUILD=1 modal run modal_run.py
#   # Or per-layer: .uv_pip_install("pkg", force_build=True)
