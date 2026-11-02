# Local platform recovery — 30 September 2026

Scope: restore email/password sign-in and the Redis job queue, then run small real jobs. This is a local verification, not a production release or certification of all 52 catalog tools.

## Restored

- Supabase sign-in succeeds after moving this Mac off the school network. The former DNS resolver returned NXDOMAIN for the project hostname. No auth bypass was added.
- Redis is running on loopback with append-only persistence in `.local/redis`. API and worker health both return `ok:true, db:true, redis:true`.
- Local configuration now uses localhost URLs, explicit Redis configuration, real worker mode, and the existing Python environment that includes Modal. Secrets were retained in the ignored `.env.local`.
- Three pending migrations were applied, bringing the database to 31. The preflight now compares checked-in migrations against applied names instead of only counting rows already recorded in the database.
- ProteinMPNN passes each staged PDB file individually to the upstream CLI; the CLI does not accept a directory in `--pdb_path`.
- ESM-2 returns its seed/done events with its remote function result. Detached function stdout is not relied upon for the result transport.
- The ProteinMPNN and ESM-2 fixes were deployed to the workspace selected by the configured Modal credentials.
- `pnpm dev:platform` starts the product app, API, worker, and local Redis; it keeps existing listeners and omits the marketing site. The local app uses Webpack because the existing Turbopack persistence cache timed out.

## Verification

- Email/password auth and authenticated project/job/design/catalog queries passed.
- Authenticated dashboard, projects, jobs, and tools pages returned HTTP 200.
- Browser sign-in completed successfully. The signed-in dashboard and jobs list were visually inspected in Chrome.
- R2 temporary-object write/read/byte comparison/cleanup passed.
- A real ESM-2 8M inference returned the expected sequence and numeric likelihood metric.
- ProteinMPNN provider-to-Modal-to-R2 smoke passed with a readable 1,201-byte sequence CIF artifact. This is a sequence artifact, not predicted atomic coordinates.
- Three authenticated API submissions passed through Redis and the worker, completed real ProteinMPNN inference, and each persisted one design:
  - `88f043cb-3148-4fdf-a030-d08443b18913` — seed 101
  - `598dfe3d-a93c-4013-9a79-d25ad74d0090` — seed 102
  - `074e8ceb-ea5a-4474-8270-b8203773232a` — seed 103
- 36 existing worker tests and two new Python contract regression tests passed.
- `pnpm dev:platform` verified against running listeners; `dev-check` reports 31/31 checked-in migrations and 52 tools.

## Remaining, outside this focused repair

- The authenticated export endpoint returns HTTP 500: Supabase reports infinite recursion in the RLS policy for `org_members`. Direct signed artifact access and app export routes are distinct checks; do not report app exports as verified.
- Google OAuth remains disabled in this environment; password sign-in is verified.
- Older queued/cancelling jobs remain in the demo account. They were not cancelled or resubmitted; their concurrency usage required sequential test submissions.
- Full catalog execution, fresh-user admission, production deployment, email delivery, and billing were not verified by this pass.

The initial diagnostic job `57079bc4-eb4d-4242-9212-4a70b32f4839` failed on the missing credential-environment column before migration; it remains as an honest diagnostic record. The three later jobs succeeded after repair.
