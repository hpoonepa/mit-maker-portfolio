-- Per-organization GPU spend tracking with a $50 hard cap (private beta).
--
-- 1. Add running-total + per-org cap columns on organizations.
-- 2. Create the gpu_spends ledger — one row per submitted job, written
--    inside the same RLS transaction that inserts the Job row. Stores the
--    submit-time estimate; the worker overwrites actual_usd / seconds_actual
--    after the job finishes (when the provider returns billable seconds).
-- 3. Enforce tenant isolation via RLS policies that mirror the rest of the
--    schema (membership-derived org check via app_current_user()).

-- ── 1. Organization columns ────────────────────────────────────────────────
ALTER TABLE organizations
  ADD COLUMN IF NOT EXISTS gpu_spend_cap_usd NUMERIC(10, 4) NOT NULL DEFAULT 50.00,
  ADD COLUMN IF NOT EXISTS gpu_spend_usd     NUMERIC(10, 4) NOT NULL DEFAULT 0;

-- ── 2. Ledger table ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gpu_spends (
  id              BIGSERIAL PRIMARY KEY,
  org_id          UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  job_id          UUID                 REFERENCES jobs(id)          ON DELETE SET NULL,
  tool            TEXT        NOT NULL,
  gpu_type        TEXT        NOT NULL,
  estimated_usd   NUMERIC(10, 4) NOT NULL,
  actual_usd      NUMERIC(10, 4),
  seconds_actual  INTEGER,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS gpu_spends_org_id_created_at_idx
  ON gpu_spends(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS gpu_spends_job_id_idx
  ON gpu_spends(job_id);
CREATE INDEX IF NOT EXISTS gpu_spends_org_id_tool_idx
  ON gpu_spends(org_id, tool);

-- ── 3. Row-level security ──────────────────────────────────────────────────
ALTER TABLE gpu_spends ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'gpu_spends' AND policyname = 'gpu_spends_tenant_isolation'
  ) THEN
    EXECUTE $POL$
      CREATE POLICY gpu_spends_tenant_isolation ON gpu_spends
        USING (org_id IN (
          SELECT org_id FROM org_members WHERE user_id = app_current_user()
        ))
        WITH CHECK (org_id IN (
          SELECT org_id FROM org_members WHERE user_id = app_current_user()
        ))
    $POL$;
  END IF;
END $$;
