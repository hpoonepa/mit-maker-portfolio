# RFdiffusion All-Atom

Papercrane's RFdiffusion All-Atom adapter generates protein backbones while
optionally conditioning on small molecules. It resolves target and ligand
artifacts from short-lived storage URLs, uploads each generated structure, and
streams NDJSON seed events to the worker.

- Modal app: `papercrane-rfdiffusionaa`
- Entrypoint: `papercrane_dispatch`
- Default GPU: A100 40 GB
- Release state: runnable beta; live production verification is still limited

Input and output contracts live in `schemas/input.json` and
`schemas/output.json`.
