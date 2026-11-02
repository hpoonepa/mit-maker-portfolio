# Paper Crane — Internal Runbook

Operator-grade incident response. Each entry: diagnosis, command, expected output.

---

## 1. Local dev — services down

**Diagnosis:** Web/API not responding on `:3002`/`:4000`. Stale node processes or port conflicts.

```bash
pnpm dev:check
```

Expected: a green table listing `web`, `api`, `worker` with `OK` status. If any row reads `DOWN`:

```bash
pnpm dev:reset && pnpm dev
```

Expected: `dev:reset` kills stragglers and clears `.turbo` cache; `pnpm dev` then prints `web ready on http://localhost:3002` and `api ready on http://localhost:4000` within ~10s.

---

## 2. Migrations failed

**Diagnosis:** Prisma migration aborted mid-apply. Schema drift or partial state.

```bash
pnpm prisma migrate status
```

Expected: lists last applied + any `failed` migration name. If a migration is marked failed:

```bash
pnpm prisma migrate resolve --rolled-back <migration_name>
```

Then fix the offending SQL in `prisma/migrations/<name>/migration.sql` and:

```bash
pnpm prisma migrate deploy
```

Expected: `All migrations have been successfully applied.`

---

## 3. Demo creds lost

**Diagnosis:** Forgot demo login. Seed script regenerates credentials and writes them to disk.

```bash
pnpm db:seed:demo
```

Expected: prints `Seeded demo user: demo@papercrane.bio` and writes `.agent-logs/20-demo-creds.txt`.

```bash
cat .agent-logs/20-demo-creds.txt
```

Expected: two lines — `email=demo@papercrane.bio` and `password=<generated>`.

---

## 4. API booting in dev with empty env

**Diagnosis:** API logs `[stub] REDIS_URL not set` or `[stub] STRIPE_SECRET_KEY not set`. This is FINE in dev.

The API ships fallback stubs:
- `REDIS_URL=""` → in-memory queue (no persistence; OK for one-shot dev)
- `STRIPE_SECRET_KEY=""` → billing routes return mocked checkout URLs
- `WORKER_DEV_MODE=true` → API processes jobs inline instead of dispatching to worker

No action needed unless you see `FATAL` — only the warnings above are expected.

---

## 5. Mol* viewer fails to load PDB

**Diagnosis:** Blank viewer or "failed to fetch structure". Either CSP blocked the RCSB CDN or RCSB is down.

```bash
curl -I https://files.rcsb.org/download/4HHB.pdb
```

Expected: `HTTP/2 200`. If non-200, RCSB is down — wait or use a cached structure.

If 200 but viewer still empty, open browser devtools → Network tab → check the structure request. CSP violations show as `Refused to connect to ...`. Verify `next.config.js` `connect-src` includes `https://files.rcsb.org` and `https://models.rcsb.org`.

The viewer renders a "Retry" button on failure — clicking it re-issues the fetch without page reload.

---

## 6. Job stuck in `queued`

**Diagnosis:** UI shows job pinned at `queued` for >30s. Either worker is not running, or `WORKER_DEV_MODE` is off without a worker.

```bash
ps aux | grep -E "papercrane.*worker" | grep -v grep
```

Expected: one process line. If empty, either start the worker:

```bash
pnpm --filter worker dev
```

Or set `WORKER_DEV_MODE=true` in `apps/api/.env.local` and restart the API:

```bash
echo "WORKER_DEV_MODE=true" >> apps/api/.env.local && pnpm --filter api dev
```

Expected: API log prints `[worker] dev mode enabled, processing jobs inline`.

---

## 7. Upload "no ATOM records"

**Diagnosis:** PDB upload rejected with `no ATOM records found`. Usually the dev stub storage path is missing or read-only.

```bash
ls -ld /tmp/papercrane-dev-stub
```

Expected: `drwxr-xr-x ... /tmp/papercrane-dev-stub`. If missing or wrong permissions:

```bash
mkdir -p /tmp/papercrane-dev-stub && chmod 755 /tmp/papercrane-dev-stub
```

Expected: directory created. Re-upload the PDB; the API writes to `/tmp/papercrane-dev-stub/<uuid>.pdb` and parses ATOM records from disk.

If still failing, the file genuinely lacks ATOM lines (e.g. CIF-only or HEADER-only). Confirm with:

```bash
grep -c "^ATOM" <your-file>.pdb
```

Expected: count > 0.

---

## 8. Auth fails (Supabase)

**Diagnosis:** Login redirects loop or `Invalid API key`. Next.js bakes `NEXT_PUBLIC_*` env vars at startup — a fresh `.env.local` is not picked up by a running server.

```bash
grep -E "NEXT_PUBLIC_SUPABASE_(URL|ANON_KEY)" apps/web/.env.local
```

Expected: both lines present and non-empty. If missing, copy from `apps/web/.env.example` and fill values from the Supabase dashboard.

After editing, restart the dev server (Ctrl-C then re-run):

```bash
pnpm --filter web dev
```

Expected: log prints `Loaded env from .env.local` and login completes.

---

## 9. CORS blocked

**Diagnosis:** Browser console: `Access to fetch at 'http://localhost:4000/...' from origin 'http://localhost:3002' has been blocked by CORS policy`.

Open `apps/api/src/config.ts` and verify `corsOrigin` includes `http://localhost:3002`:

```bash
grep -n "corsOrigin" apps/api/src/config.ts
```

Expected: a line listing localhost origins including `:3002`. If missing, add it and restart the API:

```bash
pnpm --filter api dev
```

Expected: API startup log prints `CORS allowed origins: http://localhost:3000, http://localhost:3002`.

---

## Escalation

If two runbook entries do not resolve the issue, checkpoint state and hand off:

```bash
bash /Users/harsha/Desktop/claudeprojects/CLAUDEVAULT/scripts/checkpoint.sh "incident-<short>" "<symptom + what's been tried>"
```

Then page the on-call engineer with the handoff path.
