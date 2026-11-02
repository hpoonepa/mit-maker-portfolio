-- Paper Crane — Audit log
--
-- Adds an append-only, org-scoped audit log for privileged actions
-- (API keys issued, webhooks created, members invited, subscription changes,
-- jobs cancelled, etc.). Retention is handled out-of-band by a cron:
--   - free tier: 90 days
--   - pro / frontier: 365 days
--
-- RLS:
--   - SELECT: visible to org members (same tenant-isolation pattern used
--     across the schema; keyed off `app_current_user()`).
--   - INSERT: writes go through the service role (BYPASSRLS) via
--     `@papercrane/observability#logAuditEvent`. No per-user INSERT policy is
--     defined, which means direct-from-client inserts are rejected.
--   - UPDATE / DELETE: intentionally no policies → append-only. The service
--     role can still perform retention deletes (BYPASSRLS), but no user or
--     API key can mutate a row once written.

-- ── Enum ────────────────────────────────────────────────────────────────────
CREATE TYPE "AuditAction" AS ENUM (
  'api_key.created',
  'api_key.revoked',
  'api_key.rotated',
  'webhook.created',
  'webhook.deleted',
  'webhook.secret_rotated',
  'member.invited',
  'member.removed',
  'member.role_changed',
  'subscription.upgraded',
  'subscription.downgraded',
  'subscription.cancelled',
  'job.cancelled',
  'tool_license.acknowledged',
  'org.created',
  'org.settings_updated'
);

-- ── audit_logs ──────────────────────────────────────────────────────────────
CREATE TABLE "audit_logs" (
  "id"             uuid           PRIMARY KEY DEFAULT gen_random_uuid(),
  "org_id"         uuid           NOT NULL,
  "user_id"        uuid,
  "action"         "AuditAction"  NOT NULL,
  "resource_type"  text,
  "resource_id"    text,
  "metadata"       jsonb,
  "ip_address"     inet,
  "user_agent"     text,
  "created_at"     timestamptz(6) NOT NULL DEFAULT now(),
  CONSTRAINT "audit_logs_org_id_fkey"
    FOREIGN KEY ("org_id") REFERENCES "organizations"("id")
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT "audit_logs_user_id_fkey"
    FOREIGN KEY ("user_id") REFERENCES "users"("id")
    ON DELETE SET NULL ON UPDATE CASCADE
);

-- Primary query pattern: org timeline, newest first. Matches the list tRPC
-- procedure's ordering and paginates via (created_at, id) cursor.
CREATE INDEX "audit_logs_org_id_created_at_idx"
  ON "audit_logs" ("org_id", "created_at" DESC);

-- Filter-by-user lookups in the UI.
CREATE INDEX "audit_logs_user_id_idx"
  ON "audit_logs" ("user_id");

-- Filter-by-action (multi-select in the UI).
CREATE INDEX "audit_logs_action_idx"
  ON "audit_logs" ("action");

-- ── Row-Level Security ──────────────────────────────────────────────────────
-- Append-only: SELECT for members, no UPDATE, no DELETE. The service role
-- used by the API (BYPASSRLS) is the only writer; user sessions cannot
-- INSERT directly because no INSERT policy exists.
ALTER TABLE "audit_logs" ENABLE ROW LEVEL SECURITY;

CREATE POLICY audit_logs_tenant_select ON "audit_logs"
  FOR SELECT
  USING (org_id IN (
    SELECT org_id FROM org_members WHERE user_id = app_current_user()
  ));

-- Deliberately no INSERT policy → direct-from-client writes are blocked.
-- Deliberately no UPDATE policy → rows are immutable.
-- Deliberately no DELETE policy → audit trail is append-only. Retention
-- deletes run under the service role which bypasses RLS.
