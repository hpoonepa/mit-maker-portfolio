-- Paper Crane — Postgres bootstrap script
--
-- Executed once on first container start (empty data dir) by the
-- postgres image entrypoint. Safe to re-run: every statement is IF NOT EXISTS.
-- To re-run manually after schema drift:
--   docker compose exec postgres psql -U postgres -d papercrane -f /docker-entrypoint-initdb.d/00-init.sql

-- pgcrypto: gen_random_uuid(), crypt(), digest() — needed for UUID primary keys
-- and password hashing helpers.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- citext: case-insensitive text type. Use for emails, usernames, and any
-- identifier we want to match without .lower() gymnastics in the app layer.
CREATE EXTENSION IF NOT EXISTS citext;

-- pg_stat_statements: query-level performance counters. Cheap to leave on in
-- dev so we can profile slow queries early. Requires it to also be listed in
-- shared_preload_libraries (override via docker-compose.override.yml if you
-- actually want the counters populated — the extension install is harmless
-- either way).
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
