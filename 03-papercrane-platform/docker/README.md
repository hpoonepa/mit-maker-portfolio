# Paper Crane Docker bases

Two shared base images every tool adapter inherits from. They pin the
scientific + bio Python stack to identical versions so a design run produces
the same numerics whether the tool runs on GPU or CPU.

| Image | Use when |
|-------|----------|
| [`base-cuda12`](./base-cuda12/README.md) | Tool needs CUDA (RFdiffusion, BindCraft, BoltzGen, ESM2, Boltz-2, Chai, AlphaFold, etc.). |
| [`base-cpu`](./base-cpu/README.md) | Validators, parsers, rankers, orchestration glue — anything that doesn't touch a GPU. |

Both publish to GHCR under `ghcr.io/papercrane/<image>:<tag>` and are built by
[`.github/workflows/docker-base.yml`](../.github/workflows/docker-base.yml) on
every push to `main` that touches `docker/base-**`.

## How tool authors consume these

### 1. Pick a base

```dockerfile
# GPU adapter
FROM ghcr.io/papercrane/base-cuda12:latest

# CPU adapter
FROM ghcr.io/papercrane/base-cpu:latest
```

Pin to a `sha-<8char>` tag in production so rebuilding the base doesn't silently
change your tool's numerics.

### 2. Add tool-specific deps

```dockerfile
RUN pip install --no-cache-dir rfdiffusion==1.1.0
```

Or clone a repo that isn't on PyPI:

```dockerfile
RUN git clone --depth 1 https://github.com/RosettaCommons/RFdiffusion.git /opt/rfdiffusion \
    && pip install --no-cache-dir -r /opt/rfdiffusion/requirements.txt
```

### 3. Drop in your `run.sh`

The base ships a placeholder at `/opt/papercrane/run.sh` that just prints
"override me". Replace it:

```dockerfile
COPY run.sh /opt/papercrane/run.sh
RUN chmod +x /opt/papercrane/run.sh
```

Your `run.sh` contract (see `docs/plans/02-tool-integration.md` §2–3):

- Read task spec from `/inputs` (path + format defined by your adapter schema).
- Write outputs to `/outputs` in the canonical Paper Crane result schema.
- Exit non-zero on failure.

The base already sets `ENTRYPOINT ["/opt/papercrane/run.sh"]`, so you don't
need to redeclare it unless you want different behavior.

### 4. Build & test locally

```bash
docker build -t papercrane/mytool:dev .
docker run --rm \
    -v "$PWD/example-input:/inputs:ro" \
    -v "$PWD/out:/outputs" \
    papercrane/mytool:dev
```

For GPU adapters add `--gpus all` and make sure your host has a recent NVIDIA
driver (CUDA 12.1 requires driver >= 530).

## Building the bases yourself

```bash
# from repo root
BASE_TAG=dev bash docker/build.sh
```

That builds both `ghcr.io/papercrane/base-cuda12:dev` and
`ghcr.io/papercrane/base-cpu:dev` against your local Docker daemon. Use this
when iterating on the base Dockerfiles themselves — CI handles the published
tags on `main`.

## Version policy

- **Python, PyTorch, numpy/scipy/biopython/gemmi/pandas/pydantic/pyyaml** are
  pinned to exact versions. Bumping any of these is a deliberate, reviewed
  change — it may shift design numerics downstream.
- **Base OS packages** (git, curl, wget, build-essential) track the upstream
  distro; they are rebuilt whenever the base image is rebuilt.
- Version parity between `base-cuda12` and `base-cpu` is enforced by review —
  any change to one must be mirrored in the other.
