# Modal integration status

Last updated: 2026-08-30

## Release contract

Papercrane invokes named, deployed Modal Functions through the official SDK:

```text
jobs.submit -> BullMQ -> Function.from_name(...).spawn -> NDJSON events -> R2 -> Design row
```

The token selects the Modal workspace; `MODAL_ENVIRONMENT` selects an
environment when the workspace has more than one. Missing apps are deployed
once on first use by default. Core workflow deployments can be provisioned
ahead of traffic with `pnpm modal:deploy:core`.

The production path now has these invariants:

- the worker streams seed events as they arrive instead of buffering the full run;
- multi-seed jobs split across 1–8 bounded lanes, with each lane reusing one
  container/model load for several seeds;
- cancelling a job cancels the remote FunctionCall and terminates its bridge;
- cancellation discards already-buffered lane events so no additional designs
  can be persisted after the user cancels;
- every structure seed receives an org-scoped, one-hour R2 PUT URL;
- a structure tool uploads bytes before it emits the seed event;
- uploaded targets are passed as short-lived GET URLs;
- uploaded partners in two-structure jobs are passed as separate short-lived,
  org-scoped GET URLs;
- uploaded ligand files are passed as short-lived, org-scoped GET URLs;
- missing R2 configuration fails closed instead of persisting a phantom key;
- signed URLs are redacted from command logs and metadata;
- manifest defaults are merged before execution, with the submitted canonical
  target, chain, sequence, ligand, and seed fields always taking precedence;
- tool-specific parameters are validated against the embedded manifest input
  schema before quota reservation, billing, or queue writes;
- Modal OOM, timeout, and infrastructure codes are retryable.

## Tool status

The internal adapter registry contains 52 slugs. All 52 have a Modal source app.
Twelve tools are GA and 39 are submission-enabled beta integrations. Beta means
the source contract is complete but live production verification is limited;
the UI labels that distinction. Germinal remains catalog-only because its image
still pins a zeroed upstream SHA and explicitly identifies itself as a stub.
RFD3, AntiFold, ThermoMPNN, and PDBFixer were added on 2026-08-10 and must pass
remote image/checkpoint and R2 artifact smoke tests before GA promotion. RF3,
ESMFold, and DISCO were
added the same day with the same beta gate; DISCO additionally needs an H100
memory smoke test for its non-CUTLASS attention fallback.
ESM-IF1, EvoEF2, OmegaFold, ImmuneBuilder, and OpenMM Relax were added the same
day and remain beta until their pinned images, checkpoints, and R2 artifacts pass
live smoke tests. EvoEF2 uses NeuroSnap's open Python implementation.
Foldseek, P2Rank, FreeSASA, AutoDock Vina, and PLIP were added the same day as
CPU-first structure search, pocket detection, surface analysis, docking, and
interaction-profiling adapters. They remain beta until their pinned binaries,
dependency images, and R2 artifacts pass live smoke tests.
MMseqs2, HMMER, MAFFT, DSSP, fpocket, MDAnalysis, PDB2PQR, PROPKA, APBS, and
smina were added on 2026-08-11 as CPU-first sequence, structure, electrostatics,
preparation, pocket, and docking adapters. They remain beta until their pinned
binaries, dependency images, and R2 artifacts pass live smoke tests.
ProtParam, Parasail, CD-HIT, DIAMOND, HH-suite, ProDy, pdb-tools, PRODIGY,
PDBe Arpeggio, and DockQ were added on 2026-08-11 as CPU-first sequence,
clustering, dynamics, cleanup, contact, affinity, and model-quality adapters.
They remain beta until their pinned binaries, dependency images, and signed
mmCIF artifact paths pass live smoke tests.

The GA subset contains:

- RFdiffusion, Chroma, BindCraft, and BoltzGen
- ProteinMPNN, LigandMPNN, and SolubleMPNN
- Boltz-1, Boltz-2, Chai-1, and AlphaFold3-compatible prediction through Protenix
- ESM-2

The dashboard and public tool-list API also surface the 39 runnable beta tools
described above, with explicit beta badges and the same submission path. They
must not be described as GA until their remote smoke gates pass.

Chroma's upstream public checkpoint requires a Generate Biomedicines access
token. Store it as `CHROMA_API_KEY` in a Modal secret and set
`CHROMA_MODAL_SECRET` to the secret name on the worker.

## Verification commands

```bash
# No GPU spend: validates all registered source files and entrypoints.
pnpm modal:check

# External write + potential image build cost: deploy the three workflow apps.
pnpm modal:deploy:core

# Live: runs ESM-2 8M against sequence "M" through the exact worker adapter.
pnpm modal:smoke

# Worker and storage regression suites.
pnpm --filter @papercrane/worker typecheck
pnpm --filter @papercrane/worker test
pnpm --filter @papercrane/storage test
pnpm --filter @papercrane/trpc test
```

After changing a manifest schema or its defaults, refresh the database-backed
catalog with `pnpm db:seed:tools`. The seed stores the schema JSON itself rather
than a filesystem `$ref`, so the API image does not need the worker-only
`tools/` tree and the dashboard can render typed parameter controls.

On 2026-07-11, a live ESM-2 8M call authenticated, built the image, ran on
Modal, and emitted one `seed` plus one `done` event. A later retry encountered a
Modal control-plane heartbeat failure after startup; treat that code as
retryable and do not represent an individual successful run as an availability
guarantee.

On 2026-08-24, the same smoke command failed before image startup with
`Could not connect to the Modal server`; every local Modal profile reported as
misconfigured. Static dispatch checks still pass for all 52 tools. Repair the
workspace token/profile and repeat a one-seed smoke before any beta tool is
promoted to GA.

## Required production configuration

```text
MODAL_TOKEN_ID
MODAL_TOKEN_SECRET
MODAL_CREDENTIAL_ENCRYPTION_KEY
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET
REDIS_URL
DATABASE_URL
```

`PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS=1` exists only for explicit local
experiments. Never set it in a shared or production environment.

## Remaining work

- Replace the legacy `modalClient.ts` test shim; production does not use its
  assumed REST endpoints.
- Persist provider-native runtime/cost from Modal call metadata. RunPod remains
  config-only and must not be selected until a real provider implementation and
  equivalent artifact tests exist.
- Add a production-contract test with a real R2 test bucket: upload a known
  target, submit one beta job, verify the object checksum, load the design URL,
  then delete the fixture.
- Move the application-managed AES-256 credential key into a managed KMS before
  broader BYOK rollout.
