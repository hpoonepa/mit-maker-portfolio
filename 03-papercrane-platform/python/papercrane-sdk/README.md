# papercrane-sdk

Python SDK for Paper Crane tool adapters — the base classes that tool containers
(BindCraft, RFdiffusion, ProteinMPNN, BoltzGen, …) import to wire their CLI
entrypoint into the Paper Crane orchestrator.

Mirrors the TypeScript `@papercrane/tools-sdk` contract. Same JSON wire format,
same adapter lifecycle (`validate` → `prepare` → `run` → `parse`), same
`ToolManifest` schema.

## Install (local dev, inside a tool container)

```bash
pip install -e ./python/papercrane-sdk
```

From a tool's `Dockerfile`:

```dockerfile
COPY python/papercrane-sdk /opt/papercrane-sdk
RUN pip install -e /opt/papercrane-sdk
```

## Usage

```python
# tools/bindcraft/adapter.py
from papercrane_sdk import Adapter, DesignRequest, DesignResult, ToolManifest, run_cli

class BindCraftAdapter(Adapter):
    manifest = ToolManifest.model_validate_json(open("manifest.json").read())

    def prepare(self, req: DesignRequest, workdir):
        # stage tool-specific config files; return anything run() needs
        ...

    def run(self, job):
        # spawn the tool inside this container
        ...

    def parse(self, raw) -> DesignResult:
        # read tool outputs, normalize into DesignResult
        ...


if __name__ == "__main__":
    raise SystemExit(run_cli(BindCraftAdapter))
```

And in `run.sh` (the container ENTRYPOINT invocation):

```bash
#!/usr/bin/env bash
set -euo pipefail
python /opt/papercrane/adapter.py \
  --request /inputs/request.json \
  --target /inputs/target.pdb \
  --output /outputs
```

## Wire format

JSON on the wire is **camelCase** to stay byte-compatible with the TypeScript
orchestrator. Python code uses **snake_case** internally — the models handle
both via pydantic field aliases (`populate_by_name=True`).

## Public API

| Name                 | Kind        | Purpose                                                      |
|----------------------|-------------|--------------------------------------------------------------|
| `Adapter`            | ABC         | Base class for container tools; implement `prepare/run/parse`|
| `RemoteAdapter`      | ABC         | Base class for closed-weight HTTPS tools                     |
| `DesignRequest`      | model       | Normalized input, parsed from `/inputs/request.json`         |
| `DesignResult`       | model       | Normalized output, written to `/outputs/result.json`         |
| `Residue`            | model       | `{chain, resi}` hotspot residue                              |
| `DesignConstraints`  | model       | Length/disulfide/solubility knobs                            |
| `ToolManifest`       | model       | Tool metadata (id, image, compute, tier)                     |
| `ValidationError`    | model       | `{field, message}` from `validate()`                         |
| `run_cli`            | function    | One-liner entrypoint for tool `run.sh`                       |
