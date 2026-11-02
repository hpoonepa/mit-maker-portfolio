-- Paper Crane — Apply RLS post-init (idempotent).
--
-- The original RLS bootstrap lives at 00000000000000_enable_rls/migration.sql
-- and predates the init migration in lexicographic order. To make a fresh
-- `prisma migrate deploy` work end-to-end, the original file's statements were
-- wrapped in IF EXISTS guards so it no-ops on a fresh DB. This file then
-- re-runs the same statements idempotently AFTER the init + extension
-- migrations have created every table the policies reference (notably
-- `webhooks`, `webhook_deliveries`, `job_audits`, `idempotency_keys` which
-- carry their own RLS in 20260423120000_add_webhook_audit_idempotency, plus
-- the base tables created by 20260423000000_init).
--
-- On already-baselined production DBs this migration is detected as new but
-- every guard short-circuits because the policies/objects already exist.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Partial / functional indexes Prisma can't express ──────────────────────
CREATE UNIQUE INDEX IF NOT EXISTS api_keys_hash_active_unique
  ON api_keys (hash) WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS designs_metrics_gin
  ON designs USING GIN (metrics);

CREATE INDEX IF NOT EXISTS jobs_retention_sweep
  ON jobs (expires_at) WHERE status IN ('succeeded', 'failed');

-- ── Helper: resolve the current user id from a GUC ─────────────────────────
CREATE OR REPLACE FUNCTION app_current_user() RETURNS uuid AS $$
  SELECT NULLIF(current_setting('app.current_user', true), '')::uuid;
$$ LANGUAGE sql STABLE;

-- ── Enable RLS + tenant isolation policies ─────────────────────────────────
-- Pattern: a row is visible iff its org_id is in the caller's org memberships.

ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'projects' AND policyname = 'projects_tenant_isolation') THEN
    EXECUTE $POL$
      CREATE POLICY projects_tenant_isolation ON projects
        USING (org_id IN (
          SELECT org_id FROM org_members WHERE user_id = app_current_user()
        ))
    $POL$;
  END IF;
END $$;

ALTER TABLE targets ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'targets' AND policyname = 'targets_tenant_isolation') THEN
    EXECUTE $POL$
      CREATE POLICY targets_tenant_isolation ON targets
        USING (org_id IN (
          SELECT org_id FROM org_members WHERE user_id = app_current_user()
        ))
    $POL$;
  END IF;
END $$;

ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'jobs' AND policyname = 'jobs_tenant_isolation') THEN
    EXECUTE $POL$
      CREATE POLICY jobs_tenant_isolation ON jobs
        USING (org_id IN (
          SELECT org_id FROM org_members WHERE user_id = app_current_user()
        ))
    $POL$;
  END IF;
END $$;

ALTER TABLE designs ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'designs' AND policyname = 'designs_tenant_isolation') THEN
    EXECUTE $POL$
      CREATE POLICY designs_tenant_isolation ON designs
        USING (org_id IN (
          SELECT org_id FROM org_members WHERE user_id = app_current_user()
        ))
    $POL$;
  END IF;
END $$;

ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'api_keys' AND policyname = 'api_keys_tenant_isolation') THEN
    EXECUTE $POL$
      CREATE POLICY api_keys_tenant_isolation ON api_keys
        USING (org_id IN (
          SELECT org_id FROM org_members WHERE user_id = app_current_user()
        ))
    $POL$;
  END IF;
END $$;

ALTER TABLE usage_seeds ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'usage_seeds' AND policyname = 'usage_seeds_tenant_isolation') THEN
    EXECUTE $POL$
      CREATE POLICY usage_seeds_tenant_isolation ON usage_seeds
        USING (org_id IN (
          SELECT org_id FROM org_members WHERE user_id = app_current_user()
        ))
    $POL$;
  END IF;
END $$;

ALTER TABLE org_members ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'org_members' AND policyname = 'org_members_self_visibility') THEN
    EXECUTE $POL$
      CREATE POLICY org_members_self_visibility ON org_members
        USING (org_id IN (
          SELECT org_id FROM org_members WHERE user_id = app_current_user()
        ))
    $POL$;
  END IF;
END $$;

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'users' AND policyname = 'users_self_visibility') THEN
    EXECUTE $POL$
      CREATE POLICY users_self_visibility ON users
        USING (
          id = app_current_user()
          OR id IN (
            SELECT user_id FROM org_members
            WHERE org_id IN (
              SELECT org_id FROM org_members WHERE user_id = app_current_user()
            )
          )
        )
    $POL$;
  END IF;
END $$;

ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'organizations' AND policyname = 'organizations_member_visibility') THEN
    EXECUTE $POL$
      CREATE POLICY organizations_member_visibility ON organizations
        USING (id IN (
          SELECT org_id FROM org_members WHERE user_id = app_current_user()
        ))
    $POL$;
  END IF;
END $$;
