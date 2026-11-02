-- Paper Crane — Row-Level Security bootstrap (idempotent, ordering-tolerant).
--
-- This migration originally assumed the base tables already existed. Because
-- Prisma applies migrations in lexicographic order and this directory's
-- timestamp (00000000000000) precedes the init migration, every statement here
-- has been wrapped with `IF EXISTS` / `DO $$ ... END $$` guards so it is safe
-- to run BEFORE init (no-ops on a fresh DB) and safe to re-run AFTER init.
--
-- The actual RLS bootstrap is duplicated in
--   20260427130000_apply_rls/migration.sql
-- which runs after the init migration and idempotently applies these same
-- statements. On a fresh `prisma migrate deploy`:
--   1. 00000000000000_enable_rls       → all guards skip (no tables yet); recorded applied
--   2. 20260423000000_init             → creates base tables
--   3. 20260423110000_…                → schema additions
--   ...
--   N. 20260427130000_apply_rls        → enables RLS + policies (the real work)
--
-- On already-baselined production DBs (where the original 00000000000000_enable_rls
-- ran via psql), this file is unchanged in effect because every guard either
-- detects the existing object (CREATE EXTENSION / CREATE INDEX IF NOT EXISTS /
-- CREATE OR REPLACE FUNCTION) or is gated on the table existing.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Partial / functional indexes Prisma can't express ──────────────────────
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'api_keys') THEN
    CREATE UNIQUE INDEX IF NOT EXISTS api_keys_hash_active_unique
      ON api_keys (hash) WHERE revoked_at IS NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'designs') THEN
    CREATE INDEX IF NOT EXISTS designs_metrics_gin
      ON designs USING GIN (metrics);
  END IF;
END $$;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'jobs') THEN
    CREATE INDEX IF NOT EXISTS jobs_retention_sweep
      ON jobs (expires_at) WHERE status IN ('succeeded', 'failed');
  END IF;
END $$;

-- ── Helper: resolve the current user id from a GUC ─────────────────────────
CREATE OR REPLACE FUNCTION app_current_user() RETURNS uuid AS $$
  SELECT NULLIF(current_setting('app.current_user', true), '')::uuid;
$$ LANGUAGE sql STABLE;

-- ── Enable RLS + tenant isolation policies ─────────────────────────────────
-- Pattern: a row is visible iff its org_id is in the caller's org memberships.

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'projects') THEN
    EXECUTE 'ALTER TABLE projects ENABLE ROW LEVEL SECURITY';
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'projects' AND policyname = 'projects_tenant_isolation') THEN
      EXECUTE $POL$
        CREATE POLICY projects_tenant_isolation ON projects
          USING (org_id IN (
            SELECT org_id FROM org_members WHERE user_id = app_current_user()
          ))
      $POL$;
    END IF;
  END IF;
END $$;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'targets') THEN
    EXECUTE 'ALTER TABLE targets ENABLE ROW LEVEL SECURITY';
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'targets' AND policyname = 'targets_tenant_isolation') THEN
      EXECUTE $POL$
        CREATE POLICY targets_tenant_isolation ON targets
          USING (org_id IN (
            SELECT org_id FROM org_members WHERE user_id = app_current_user()
          ))
      $POL$;
    END IF;
  END IF;
END $$;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'jobs') THEN
    EXECUTE 'ALTER TABLE jobs ENABLE ROW LEVEL SECURITY';
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'jobs' AND policyname = 'jobs_tenant_isolation') THEN
      EXECUTE $POL$
        CREATE POLICY jobs_tenant_isolation ON jobs
          USING (org_id IN (
            SELECT org_id FROM org_members WHERE user_id = app_current_user()
          ))
      $POL$;
    END IF;
  END IF;
END $$;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'designs') THEN
    EXECUTE 'ALTER TABLE designs ENABLE ROW LEVEL SECURITY';
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'designs' AND policyname = 'designs_tenant_isolation') THEN
      EXECUTE $POL$
        CREATE POLICY designs_tenant_isolation ON designs
          USING (org_id IN (
            SELECT org_id FROM org_members WHERE user_id = app_current_user()
          ))
      $POL$;
    END IF;
  END IF;
END $$;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'api_keys') THEN
    EXECUTE 'ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY';
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'api_keys' AND policyname = 'api_keys_tenant_isolation') THEN
      EXECUTE $POL$
        CREATE POLICY api_keys_tenant_isolation ON api_keys
          USING (org_id IN (
            SELECT org_id FROM org_members WHERE user_id = app_current_user()
          ))
      $POL$;
    END IF;
  END IF;
END $$;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'usage_seeds') THEN
    EXECUTE 'ALTER TABLE usage_seeds ENABLE ROW LEVEL SECURITY';
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'usage_seeds' AND policyname = 'usage_seeds_tenant_isolation') THEN
      EXECUTE $POL$
        CREATE POLICY usage_seeds_tenant_isolation ON usage_seeds
          USING (org_id IN (
            SELECT org_id FROM org_members WHERE user_id = app_current_user()
          ))
      $POL$;
    END IF;
  END IF;
END $$;

-- Org membership visibility: a user sees members of orgs they belong to.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'org_members') THEN
    EXECUTE 'ALTER TABLE org_members ENABLE ROW LEVEL SECURITY';
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'org_members' AND policyname = 'org_members_self_visibility') THEN
      EXECUTE $POL$
        CREATE POLICY org_members_self_visibility ON org_members
          USING (org_id IN (
            SELECT org_id FROM org_members WHERE user_id = app_current_user()
          ))
      $POL$;
    END IF;
  END IF;
END $$;

-- Users table: a user sees themselves and co-members of their orgs.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users') THEN
    EXECUTE 'ALTER TABLE users ENABLE ROW LEVEL SECURITY';
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
  END IF;
END $$;

-- Organizations: visible to members only.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'organizations') THEN
    EXECUTE 'ALTER TABLE organizations ENABLE ROW LEVEL SECURITY';
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'organizations' AND policyname = 'organizations_member_visibility') THEN
      EXECUTE $POL$
        CREATE POLICY organizations_member_visibility ON organizations
          USING (id IN (
            SELECT org_id FROM org_members WHERE user_id = app_current_user()
          ))
      $POL$;
    END IF;
  END IF;
END $$;
