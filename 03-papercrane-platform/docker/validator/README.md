# Paper Crane validator image

Computes the Paper Crane canonical metric suite on any tool's raw designs.

Runs as **stage 2** of the pipeline: some upstream container (BindCraft,
RFdiffusion, Boltz-2, …) writes designs to `/outputs/*.pdb` and emits a
manifest describing them; the validator then reads that manifest and scores
every design against the same metric set regardless of which tool produced
them. That split (see [`docs/plans/02-tool-integration.md` §5](../../docs/plans/02-tool-integration.md)) is what keeps numbers comparable across tool versions and lets us re-score historical jobs when a new metric is added.

## Contract

### Input — `/inputs/designs.json`

```json
{
  "target_pdb": "/outputs/target.pdb",
  "target_chain": "A",
  "binder_chain": "B",
  "hotspots": [
    {"chain": "A", "resi": 42},
    {"chain": "A", "resi": 57}
  ],
  "designs": [
    {
      "path": "/outputs/design_0001.pdb",
      "seed": 42,
      "upstream_metrics": {
        "iptm": 0.82,
        "plddt": 86.4,
        "i_pae": 7.1,
        "sequence": "MEEPQSDPSVEPPLS..."
      }
    }
  ]
}
```

`target_chain` defaults to `"A"` and `binder_chain` to `"B"` when omitted.
`hotspots` may be empty; the hotspot-contact metric then returns 0.0 and the
downstream `overath` composite absorbs that zero without a runtime error.

### Output — `/outputs/validated.json`

```json
{
  "target_pdb": "/outputs/target.pdb",
  "target_chain": "A",
  "binder_chain": "B",
  "hotspots": [{"chain": "A", "resi": 42}, {"chain": "A", "resi": 57}],
  "designs": [
    {
      "path": "/outputs/design_0001.pdb",
      "seed": 42,
      "upstream_metrics": { "iptm": 0.82, "plddt": 86.4, "i_pae": 7.1, "sequence": "..." },
      "metrics": {
        "ipsae":           0.79,
        "dockq":           0.67,
        "ptmenergy":       0.20,
        "lis":             0.73,
        "overath":         0.71,
        "hotspot_contact": 1.00,
        "esm_pll":        -0.32
      }
    }
  ]
}
```

A metric that fails mid-run (e.g. DockQ cannot find its binary) is written
out as `-1.0` rather than omitted — downstream filters key on the sentinel.
**Per-design metric failures do NOT fail the container.** The CLI only exits
non-zero when the input manifest is malformed, the output directory is
unwritable, or the Python import chain breaks.

### Invocation

Production:

```bash
docker run --rm --gpus all \
    -v /local/inputs:/inputs:ro \
    -v /local/outputs:/outputs \
    -v /local/weights/esm2:/opt/papercrane/weights/esm2:ro \
    ghcr.io/papercrane/validator:<tag>
```

The weights mount is optional — if it's empty the `esm_pll` metric falls
back to a length/composition heuristic (see `src/papercrane_validator/metrics/esm_pll.py`).

Local dev:

```bash
cd docker/validator
docker build -t papercrane/validator:dev .
docker run --rm \
    -v "$PWD/tests/fixtures:/inputs:ro" \
    -v "$PWD/.tmp-out:/outputs" \
    papercrane/validator:dev
cat .tmp-out/validated.json
```

CI smoke test (overrides entrypoint):

```bash
docker run --rm --entrypoint pytest \
    papercrane/validator:dev /opt/papercrane/validator/tests
```

## Metrics status

| Metric            | Implementation        | Why it's a placeholder (if so) |
|-------------------|-----------------------|-------------------------------|
| `hotspot_contact` | **Real** (gemmi)      | — |
| `ipsae`           | Placeholder           | Needs PAE matrix path in contract (PC-0042). |
| `dockq`           | Placeholder           | No reference complex for de novo binders; DockQ pkg not on PyPI (PC-0043). |
| `ptmenergy`       | Placeholder           | Needs per-residue pTM matrix. |
| `lis`             | Placeholder           | Needs PAE matrix. |
| `overath`         | Placeholder weights   | Fitted coefficients not yet mounted. |
| `esm_pll`         | Real when weights mounted, heuristic otherwise | 2.5 GB weights volume is mounted at runtime, not baked into the image. |

Track the "TODO: implement per …" comments in each `metrics/*.py` module to
see exactly what needs to land for a metric to graduate from placeholder to
real.

## Runtime sizing

- **GPU**: A10 or T4 (16 GB VRAM) is plenty — ESM2 650M is the only
  GPU-bound step today.
- **CPU**: 2 cores, 4 GB RAM.
- **Time per design**: ~1 s for placeholders; +~0.5 s for real ESM2 pLL on
  an A10.

## Layout

```
docker/validator/
├── Dockerfile
├── README.md                    <-- you are here
├── requirements.txt
├── run.sh                       <-- overrides base-cuda12 placeholder
├── src/papercrane_validator/
│   ├── __init__.py
│   ├── validate.py              <-- CLI: python -m papercrane_validator.validate
│   ├── orchestrator.py
│   └── metrics/
│       ├── __init__.py
│       ├── dockq.py
│       ├── esm_pll.py
│       ├── hotspot.py           <-- real implementation
│       ├── ipsae.py
│       ├── lis.py
│       ├── overath.py
│       └── ptmenergy.py
└── tests/
    ├── __init__.py
    ├── test_hotspot.py
    ├── test_orchestrator.py
    └── fixtures/
        ├── target.pdb
        ├── design_0001.pdb
        └── upstream_output.json
```
