# @papercrane/db

Prisma schema and client for Paper Crane. Owns the canonical data model for
plan 01 §3 (Organization, User, OrgMember, Project, Target, Job, Design,
ApiKey, UsageSeed), plus billing (Subscription), policy (FeatureFlag), tool
catalog (Tool), and benchmark tables (BenchmarkRun, BenchmarkSubmission).

## Install

The package is part of the pnpm workspace — it's already a dependency of
`apps/api`, `apps/worker`, and `apps/web`. Nothing to install here.

## Environment

```
DATABASE_URL=postgres://...   # pooled connection (pgbouncer)
DIRECT_URL=postgres://...     # unpooled; used by `prisma migrate`
```

## Usage

```ts
import { prisma, withRlsUser, type Db } from "@papercrane/db";

// Non-tenant query (admin / service-role context)
const tools = await prisma.tool.findMany({ where: { active: true } });

// Tenant-scoped query with RLS current_user set
const jobs = await withRlsUser(prisma, req.auth.userId, (tx) =>
  tx.job.findMany({ where: { orgId: req.auth.orgId } })
);

const j: Db.JobRow = jobs[0]!;
```

`withRlsUser` opens an interactive transaction, issues
`set_config('app.current_user', <uid>, true)` (the SET LOCAL form), and runs
your callback inside that transaction. The GUC is cleared automatically at
commit or rollback.

## Row-Level Security

Prisma doesn't manage RLS. Policies are applied via the hand-written
migration:

```
prisma/migrations/00000000000000_enable_rls/migration.sql
```

Every tenant table (`projects`, `targets`, `jobs`, `designs`, `api_keys`,
`usage_seeds`, `org_members`, `users`, `organizations`) has
`ALTER TABLE ... ENABLE ROW LEVEL SECURITY` plus a tenant-isolation policy
that checks membership via `app_current_user()` (a helper function that
reads the GUC).

The API service role has `BYPASSRLS`. Policies defend against direct
Supabase-client queries, which are the only ones that hit them in prod.

## Scripts

```bash
pnpm --filter @papercrane/db db:generate   # regenerate Prisma client
pnpm --filter @papercrane/db db:migrate    # create + apply a dev migration
pnpm --filter @papercrane/db db:seed       # seed local dev data
pnpm --filter @papercrane/db test          # vitest
```

### Creating the initial schema locally or in production

The migration set is self-contained and ordering-correct — `prisma migrate
deploy` works against a fresh, empty Postgres with no manual recovery:

```bash
# 1. Generate the Prisma client
pnpm --filter @papercrane/db db:generate

# 2. Apply every migration (creates tables + enables RLS + policies)
pnpm --filter @papercrane/db exec prisma migrate deploy

# 3. Seed a dev org
pnpm --filter @papercrane/db db:seed
```

#### How RLS ordering is solved

The original `00000000000000_enable_rls/migration.sql` predated the init
migration in lexicographic order, so `migrate deploy` against an empty DB used
to fail with P3018 ("relation does not exist"). To fix this without breaking
already-baselined production DBs:

1. `00000000000000_enable_rls/migration.sql` was made fully idempotent and
   ordering-tolerant — every `ALTER TABLE … ENABLE RLS` and `CREATE POLICY` is
   wrapped in a `DO $$ IF EXISTS … END $$` block. On a fresh DB it no-ops
   (tables don't exist yet); on an existing DB it's a no-op too (policies
   already exist).
2. `20260423000000_init/migration.sql` was added — the canonical baseline that
   creates every table needed before later additive migrations. It was derived
   from `prisma migrate diff --from-empty --to-schema-datamodel`, then trimmed
   so it only contains objects that existed when the schema was first frozen
   (later columns/tables/enums are layered on by their own migrations).
3. `20260427130000_apply_rls/migration.sql` was added — runs the same RLS
   bootstrap idempotently AFTER all tables exist. This is where RLS actually
   gets enabled on a fresh DB. On already-baselined prod, every guard
   short-circuits.

**Do not rename or delete `00000000000000_enable_rls/`.** Existing production
databases have it recorded in `_prisma_migrations`; removing it would force a
manual `prisma migrate resolve` dance.

## Schema notes

- All tenant tables carry an `org_id` UUID with a covering index
  `(org_id, created_at desc)`.
- `designs` has a unique constraint on `(job_id, seed)`; a seed can only be
  recorded once per job.
- `api_keys.hash` is hashed with argon2id by the API layer; the partial
  unique index `(hash) WHERE revoked_at IS NULL` is created in the RLS
  migration because Prisma 5 cannot express partial uniques.
- `designs.metrics` is JSONB with a GIN index (also in the RLS migration)
  so filter queries like `metrics @> '{"ipsae": 0.7}'` stay fast.
- `Tool.id` is a slug (e.g. `rfdiffusion`) and uses `cuid()` only as a
  placeholder default; seeds should always set it explicitly.
- Enums are Postgres-native, not strings — Prisma maps `OrgTier`, `JobStatus`,
  etc. to `CREATE TYPE` on migrate.

## Testing

```bash
pnpm --filter @papercrane/db test
```

Tests live in `tests/`:

- `client.test.ts` — verifies the singleton pattern.
- `rls.test.ts` — verifies `setCurrentUser` uses parameterized SQL (not
  string interpolation) and that `withRlsUser` wraps the work in a
  transaction.

No live database is required — the rls tests mock `$executeRaw` and
`$transaction`.
