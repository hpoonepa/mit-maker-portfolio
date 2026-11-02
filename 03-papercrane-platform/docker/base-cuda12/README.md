# base-cuda12

GPU base image for Paper Crane tool adapters. Use this when your tool needs CUDA
(inference, structure prediction, diffusion, etc.).

## Image

```
ghcr.io/papercrane/base-cuda12:<tag>
```

Published tags:

- `latest` — tip of `main`
- `sha-<8char>` — pinned to a git commit

## Preinstalled

| Layer | Contents |
|-------|----------|
| Base  | `nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04` |
| Python | 3.11 (system), pip 24.0 |
| System | git, build-essential, wget, curl, ca-certificates |
| Torch | `torch==2.3.1`, `torchvision==0.18.1` (cu121 wheels) |
| Scientific | `numpy==1.26.4`, `scipy==1.11.4`, `pandas==2.2.2` |
| Bio | `biopython==1.83`, `gemmi==0.6.5` |
| Utility | `requests==2.32.3`, `boto3==1.34.131`, `tqdm==4.66.4`, `pydantic==2.7.1`, `pyyaml==6.0.1` |

Filesystem:

- `/inputs` — mount read-only; adapters read task payloads from here.
- `/outputs` — writable; adapters drop artifacts (PDBs, CIFs, JSON) here.
- `/opt/papercrane/run.sh` — default entrypoint stub (see below).

## Size target

Final image should stay under **8 GB**. If you are building a downstream adapter
that pushes past this, split heavy weights into a separate layer mounted at
runtime rather than baked in.

## Extending

Minimal tool adapter Dockerfile:

```dockerfile
FROM ghcr.io/papercrane/base-cuda12:latest

# Tool-specific deps
RUN pip install --no-cache-dir mytool==1.2.3

# Your runner
COPY run.sh /opt/papercrane/run.sh
RUN chmod +x /opt/papercrane/run.sh

# ENTRYPOINT is already /opt/papercrane/run.sh — no need to redeclare
# unless you want a different shape.
```

Your `run.sh` should:

1. Parse task spec from `/inputs` (JSON/YAML — adapter's choice).
2. Invoke the tool.
3. Write outputs to `/outputs` in the schema defined by `docs/plans/02-tool-integration.md`.
4. Exit non-zero on failure so the scheduler marks the job failed.

## Local build

```bash
# from repo root
BASE_TAG=dev bash docker/build.sh
```

## Notes

- Image uses `ENTRYPOINT` not `CMD` so `docker run ... --entrypoint bash` still
  works for debugging.
- No CUDA toolkit (`nvcc`) — this is a *runtime* base. If you need to compile
  CUDA kernels inside the container, swap the base to `-devel` in your adapter.
