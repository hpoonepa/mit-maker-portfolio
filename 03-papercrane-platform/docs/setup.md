# Local setup

The platform uses Node, pnpm, Postgres and Supabase authentication. Docker Compose supplies Postgres, Redis and MinIO; it does not start Supabase Auth. Use a Supabase project you control, or configure a separate local Supabase instance.

The workspace declares Node `>=20.15.0` and pnpm `9.12.3`. Static dispatch checks used Node `22.22.2`; the current Next.js dependencies are `^16.2.4`. Use Node 22 for this snapshot.

From this folder:

```sh
corepack enable
corepack prepare pnpm@9.12.3 --activate
pnpm install --frozen-lockfile
cp .env.example .env.local
```

Fill in `DATABASE_URL`, `DIRECT_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, and `SUPABASE_SERVICE_ROLE_KEY` in the private `.env.local`. The database URLs must point to the database you intend to use. Keep the service-role key on the server. Set `WORKER_DEV_MODE=true` for synthetic development jobs, and label their outputs as simulated.

Start local infrastructure and initialize that local database:

```sh
docker compose up -d postgres redis
pnpm db:generate
pnpm db:migrate
pnpm db:seed
pnpm dev
```

`db:migrate` changes the configured database; check the connection before running it. The seed creates development records. Supabase authentication and redirect settings must match your local application origin. See [Supabase setup](supabase-oauth-setup.md).

| Service | Address |
|---|---|
| Public website | http://localhost:3000 |
| Dashboard | http://localhost:3002 |
| API health | http://localhost:3001/healthz |
| Worker health | http://localhost:9090/healthz |
| Documentation, started separately | http://localhost:3004 |

`pnpm dev` starts the website, dashboard, API and worker. The website first installs and builds its vendored Astro landing page; an uncached install requires network access. Start docs with `pnpm --filter @papercrane/docs dev`.

`pnpm dev:platform` expects the original machine's sibling `papercrane-website/kriss-replica` checkout at port 4444 and forces real worker mode. Use the standard `pnpm dev` path for this standalone snapshot.

These checks exercise local code without launching GPU jobs:

```sh
pnpm modal:check
pnpm --filter @papercrane/worker exec vitest run tests/modalRunner.test.ts tests/modalCredentials.test.ts tests/transitions.test.ts
```

The refresh passed both checks using the installed Intel Node 26 test runtime. An explicit ARM Node 22 test rerun passed all 18 assertions but exited with a Prisma native-engine mismatch in the shared dependency installation. A fresh install and `pnpm db:generate` must match the Node architecture. Full builds, live authentication, database initialization and remote execution were not rerun during portfolio assembly. `pnpm modal:smoke` launches a real provider job and requires credentials; it is not a static check.

Real execution needs Redis, Modal credentials and SDK, deployed functions, and R2 artifact storage. Some upstream models also require access tokens or license approval. Keep credentials outside the portfolio. [Modal integration notes](modal-integrations.md) describe the execution contract and remaining cloud verification.
