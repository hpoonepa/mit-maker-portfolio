# Local dev stack (`docker/dev/`)

This directory supports the local Paper Crane development stack defined in
`/docker-compose.yml`. It contains initialization scripts for the stateful
services — Postgres schema/extensions and MinIO bucket bootstrapping.

The stack is **dev-only**. Production uses managed Postgres, managed Redis,
and Cloudflare R2; MinIO is just a local R2 stand-in that speaks the same
S3 API.

## Prerequisites

- **Docker Desktop 4.30+** (or Colima / Orbstack / Rancher Desktop) with
  Docker Compose v2 built-in.
- ~2 GB of free disk space for images + named volumes.
- Free host ports: `5432`, `6379`, `9000`, `9001`. If any are taken, see
  "Troubleshooting" below.

Verify:

```bash
docker --version      # -> Docker version 27.x+
docker compose version # -> Docker Compose version v2.x+
```

## Bring the stack up

From the repo root (`papercrane/`):

```bash
docker compose up -d
docker compose ps        # all services should be 'healthy' after ~15s
docker compose logs -f   # tail logs; Ctrl+C to detach
```

The `minio-init` container is a one-shot — it should exit `0` after creating
the `papercrane-dev` bucket. That is expected, not an error.

## Connecting from apps

The app reads these env vars (see `.env.example`). The values below point at
the Compose stack as seen **from the host machine**:

```bash
DATABASE_URL=postgres://postgres:postgres@localhost:5432/papercrane
REDIS_URL=redis://localhost:6379

# MinIO emulates Cloudflare R2's S3 API in dev
R2_ENDPOINT=http://localhost:9000
R2_ACCESS_KEY_ID=minioadmin
R2_SECRET_ACCESS_KEY=minioadmin
R2_BUCKET=papercrane-dev
R2_FORCE_PATH_STYLE=true
```

From **inside** another Compose service, swap `localhost` for the service
name (`postgres`, `redis`, `minio`) — they all share the `papercrane` bridge
network.

The MinIO web console is at <http://localhost:9001> (login `minioadmin` /
`minioadmin`). Objects under the `public/` prefix are served anonymously at
`http://localhost:9000/papercrane-dev/public/<key>`.

## Quick sanity checks

```bash
# Postgres — should print the version
docker compose exec postgres psql -U postgres -d papercrane -c 'SELECT version();'

# Redis — should print PONG
docker compose exec redis redis-cli ping

# MinIO — list the bucket from the host
curl -s http://localhost:9000/minio/health/live && echo OK
```

## Reset (wipe all local data)

```bash
docker compose down -v   # stops services AND deletes named volumes
docker compose up -d     # fresh DB, fresh Redis, fresh MinIO
```

Use this when migrations conflict, test data gets messy, or you want to
re-run `init.sql`.

## Troubleshooting

- **Port already in use** — another process owns 5432/6379/9000/9001. Either
  stop that process (`lsof -i :5432`) or copy
  `docker-compose.override.yml.example` to `docker-compose.override.yml` and
  rebind the host-side ports there.
- **`minio-init` exits non-zero** — inspect with
  `docker compose logs minio-init`. Most failures are transient (MinIO not
  ready yet); just run `docker compose up -d minio-init` again.
- **Postgres `init.sql` changes don't take effect** — the script only runs on
  an *empty* data dir. Drop the volume: `docker compose down && docker volume
  rm papercrane-pgdata && docker compose up -d postgres`.
- **ARM (Apple Silicon) image pulls are slow** — all four images ship native
  `linux/arm64` tags; the first pull is ~500 MB total. Subsequent starts
  reuse the cache.
- **`chmod`** — if you want to run `docker/dev/minio/init.sh` directly on the
  host rather than through the sidecar, `chmod +x` it first. Inside Compose
  it's invoked as `sh /init/init.sh` so the exec bit is not required.

## See also

- `/docs/setup.md` — full developer onboarding guide
- `/docker-compose.yml` — service definitions
- `/docker-compose.override.yml.example` — template for personal overrides
- `/docker/dev/postgres/README.md` — Postgres-specific notes
