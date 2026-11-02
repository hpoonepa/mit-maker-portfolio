# base-cpu

CPU-only base image for Paper Crane tool adapters. Use this for validators,
lightweight parsers, orchestration glue, or any tool that doesn't need CUDA.

## Image

```
ghcr.io/papercrane/base-cpu:<tag>
```

Published tags:

- `latest` — tip of `main`
- `sha-<8char>` — pinned to a git commit

## Preinstalled

| Layer | Contents |
|-------|----------|
| Base  | `python:3.11-slim-bookworm` |
| System | git, build-essential, wget, curl, ca-certificates |
| Scientific | `numpy==1.26.4`, `scipy==1.11.4`, `pandas==2.2.2` |
| Bio | `biopython==1.83`, `gemmi==0.6.5` |
| Utility | `requests==2.32.3`, `boto3==1.34.131`, `tqdm==4.66.4`, `pydantic==2.7.1`, `pyyaml==6.0.1` |

No PyTorch is baked in. If your adapter needs CPU torch:

```dockerfile
FROM ghcr.io/papercrane/base-cpu:latest
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch==2.3.1
```

Versions are pinned identically to `base-cuda12`, so a tool can target either
base and pick whichever is cheaper to run.

Filesystem:

- `/inputs` — mount read-only.
- `/outputs` — writable.
- `/opt/papercrane/run.sh` — default entrypoint stub (override in adapter).

## Size target

Final image should stay under **2 GB**.

## Extending

```dockerfile
FROM ghcr.io/papercrane/base-cpu:latest

RUN pip install --no-cache-dir my-validator==0.4.0

COPY run.sh /opt/papercrane/run.sh
RUN chmod +x /opt/papercrane/run.sh
```

## Local build

```bash
# from repo root
BASE_TAG=dev bash docker/build.sh
```
