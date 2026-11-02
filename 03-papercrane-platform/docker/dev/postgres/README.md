# Postgres — local dev

This directory holds the initialization SQL for the local Postgres container
defined in `/docker-compose.yml`.

## Files

- `init.sql` — runs once on first container boot (empty `PGDATA`). Creates the
  `pgcrypto`, `citext`, and `pg_stat_statements` extensions on the
  `papercrane` database.

## When init.sql runs

Postgres' official image executes every `*.sql` / `*.sh` file in
`/docker-entrypoint-initdb.d/` **only on first startup**, i.e. when the data
directory is empty. Once the `papercrane-pgdata` volume has data in it,
changes to `init.sql` are ignored.

To force a re-init:

```bash
# from the repo root — destroys all Postgres data
docker compose down
docker volume rm papercrane-pgdata
docker compose up -d postgres
```

Or apply the script manually against a running container:

```bash
docker compose exec postgres \
  psql -U postgres -d papercrane -f /docker-entrypoint-initdb.d/00-init.sql
```

## Connection details (dev defaults)

| Setting  | Value                                               |
|----------|-----------------------------------------------------|
| Host     | `localhost` (or `postgres` from inside Compose)     |
| Port     | `5432`                                              |
| User     | `postgres`                                          |
| Password | `postgres`                                          |
| Database | `papercrane`                                        |
| URL      | `postgres://postgres:postgres@localhost:5432/papercrane` |

These credentials are intentionally weak — they are **only** for local
development. Production credentials live in the deployed environment's secret
manager and must never be checked in.

## Extensions cheatsheet

- **pgcrypto** — `SELECT gen_random_uuid();` for UUID v4 primary keys.
- **citext** — `CREATE TABLE users (email citext UNIQUE);` to avoid the
  classic `LOWER(email)` index dance.
- **pg_stat_statements** — query the `pg_stat_statements` view for top-N
  slowest queries. Needs `shared_preload_libraries=pg_stat_statements` set on
  the server (toggle via `docker-compose.override.yml`).
