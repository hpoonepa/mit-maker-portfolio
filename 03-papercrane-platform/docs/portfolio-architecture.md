# Execution and verification

A dashboard submission reaches the jobs router, which validates inputs, checks organization access, and queues work. A BullMQ worker selects the tool adapter and calls a named deployed Modal function. Progress and per-seed results stream back as NDJSON. Structure bytes go to organization-scoped R2 storage before the worker creates the design record. The dashboard then loads the result, scores and structure viewer.

The worker handles cancellation, retryable infrastructure failures, expired attempts and log redaction. `WORKER_DEV_MODE=true` replaces provider execution with synthetic output; those records must keep their simulated provenance.

The registry contains 52 entries. Source readiness configuration labels 12 GA and enables 39 beta integrations. Germinal remains catalog-only because its source image is a stub. These states do not establish current deployment availability or scientific accuracy.

## Checks run for this refresh

On 31 October 2026, with pnpm 9.12.3:

- Using Node 22.22.2, `pnpm modal:check` passed every registered source/entrypoint mapping and the runner dry-run. It launched no GPU job.
- `vitest run tests/modalRunner.test.ts tests/modalCredentials.test.ts tests/transitions.test.ts` passed 18 worker tests across three files using the installed Intel Node 26 runtime. An ARM Node 22 rerun passed those assertions but exited with a Prisma engine mismatch: the shared installed client has a `darwin` engine while ARM needs `darwin-arm64`. The source and installed dependencies were left unchanged.
- Header edits were compared with the pre-edit source using TypeScript tokens and Python ASTs. The receipt outside the project records checked files and hashes.

The stage contains current platform working-tree files, including uncommitted fixes. The refresh receipt records the canonical revision and copied file hashes. Public setup and portfolio guides were edited separately from code.

Full production builds, live Supabase sign-in, database migrations, deployment, R2 upload/download and live execution of all tools were not run during this refresh. Research and release documents describe earlier checks and remaining work; they are historical records.

The video shows real catalog interaction, BoltzGen input, and a separate saved Boltz-2 result. It is an edited recording of the application. The [SENBA guide](../dynamics/README.md) records its model and validation limits separately.
