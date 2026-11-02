-- Paper Crane benchmark database DDL.
-- Idempotent: safe to run on every invocation of the migration tool.

CREATE TABLE IF NOT EXISTS benchmark_runs (
  run_id            TEXT PRIMARY KEY,
  target_id         TEXT NOT NULL,
  tool_id           TEXT NOT NULL,
  tool_version      TEXT NOT NULL,
  config_hash       CHAR(64) NOT NULL,
  seed_start        INTEGER NOT NULL,
  seed_end          INTEGER NOT NULL,
  compute_env_hash  CHAR(64) NOT NULL,
  cost_usd          NUMERIC(10, 4) NOT NULL DEFAULT 0,
  wallclock_sec     NUMERIC(12, 2) NOT NULL DEFAULT 0,
  results_digest    CHAR(64) NOT NULL,
  source            TEXT NOT NULL,
  git_sha           TEXT,
  notes             TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT benchmark_runs_seed_range_ck
    CHECK (seed_start <= seed_end)
);

CREATE INDEX IF NOT EXISTS benchmark_runs_target_tool_idx
  ON benchmark_runs (target_id, tool_id, tool_version);

CREATE INDEX IF NOT EXISTS benchmark_runs_source_idx
  ON benchmark_runs (source);

CREATE TABLE IF NOT EXISTS designs (
  id              BIGSERIAL PRIMARY KEY,
  run_id          TEXT NOT NULL REFERENCES benchmark_runs(run_id) ON DELETE CASCADE,
  seed            INTEGER NOT NULL,
  sequence        TEXT NOT NULL,
  structure_path  TEXT NOT NULL,
  rank            INTEGER,
  metrics         JSONB NOT NULL DEFAULT '{}'::JSONB,
  CONSTRAINT designs_run_seed_uk UNIQUE (run_id, seed)
);

CREATE INDEX IF NOT EXISTS designs_run_id_idx ON designs (run_id);
CREATE INDEX IF NOT EXISTS designs_metrics_gin_idx ON designs USING GIN (metrics);
