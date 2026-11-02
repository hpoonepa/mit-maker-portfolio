-- Paper Crane — Wave 12 RLS completeness audit (idempotent).
--
-- Tables with org_id that were not yet covered by tenant-isolation RLS:
--
--   * subscriptions   — Stripe mirror; one row per org. Members read; the
--                       service role mutates via webhook handlers (which
--                       bypass RLS by design).
--   * feature_flags   — per-org policy knobs. Owners/admins should read; only
--                       admins write. Service role bypasses.
--
-- The Tool, BenchmarkRun, and BenchmarkSubmission tables remain RLS-disabled:
-- the tool catalog and benchmark leaderboard are public-read by product
-- requirement (the marketing site queries them anonymously).
--
-- Pattern: a row is visible iff its org_id is in the caller's org memberships,
-- matching the convention already established in 20260427130000_apply_rls.

ALTER TABLE "subscriptions" ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'subscriptions' AND policyname = 'subscriptions_tenant_isolation'
  ) THEN
    EXECUTE $POL$
      CREATE POLICY subscriptions_tenant_isolation ON "subscriptions"
        USING (org_id IN (
          SELECT org_id FROM org_members WHERE user_id = app_current_user()
        ))
    $POL$;
  END IF;
END $$;

ALTER TABLE "feature_flags" ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'feature_flags' AND policyname = 'feature_flags_tenant_isolation'
  ) THEN
    EXECUTE $POL$
      CREATE POLICY feature_flags_tenant_isolation ON "feature_flags"
        USING (org_id IN (
          SELECT org_id FROM org_members WHERE user_id = app_current_user()
        ))
    $POL$;
  END IF;
END $$;

-- Restrict mutations on feature_flags to org admins/owners. SELECT remains
-- open to all members through the policy above.
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'feature_flags' AND policyname = 'feature_flags_admin_write'
  ) THEN
    EXECUTE $POL$
      CREATE POLICY feature_flags_admin_write ON "feature_flags"
        FOR ALL
        USING (org_id IN (
          SELECT org_id FROM org_members
          WHERE user_id = app_current_user()
            AND role IN ('owner', 'admin')
        ))
        WITH CHECK (org_id IN (
          SELECT org_id FROM org_members
          WHERE user_id = app_current_user()
            AND role IN ('owner', 'admin')
        ))
    $POL$;
  END IF;
END $$;
