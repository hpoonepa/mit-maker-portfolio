-- Paper Crane — Webhooks, job audit trail, idempotency keys
--
-- Adds four tables flagged as missing by the Fastify API and worker:
--   1. webhooks            — per-org webhook subscriptions
--   2. webhook_deliveries  — per-attempt delivery log (child of webhooks)
--   3. job_audits          — immutable status-transition log (child of jobs)
--   4. idempotency_keys    — short-lived response cache for idempotent POSTs
--
-- RLS:
--   Webhooks and IdempotencyKey get first-class tenant-isolation policies.
--   JobAudit and WebhookDelivery inherit access through their FK parent
--   (jobs, webhooks) — a caller who cannot see the parent also cannot see
--   the child after the join, so we still enable RLS on them with a
--   parent-lookup policy for defense in depth.

-- ── webhooks ────────────────────────────────────────────────────────────────
CREATE TABLE "webhooks" (
  "id"                  uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
  "org_id"              uuid          NOT NULL,
  "url"                 text          NOT NULL,
  "events"              text[]        NOT NULL DEFAULT ARRAY[]::text[],
  "secret"              text          NOT NULL,
  "active"              boolean       NOT NULL DEFAULT true,
  "last_delivered_at"   timestamptz(6),
  "last_status_code"    integer,
  "failure_count"       integer       NOT NULL DEFAULT 0,
  "created_at"          timestamptz(6) NOT NULL DEFAULT now(),
  "updated_at"          timestamptz(6) NOT NULL DEFAULT now(),
  CONSTRAINT "webhooks_org_id_fkey"
    FOREIGN KEY ("org_id") REFERENCES "organizations"("id")
    ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX "webhooks_org_id_created_at_idx"
  ON "webhooks" ("org_id", "created_at" DESC);
CREATE INDEX "webhooks_active_idx"
  ON "webhooks" ("active");

-- ── webhook_deliveries ──────────────────────────────────────────────────────
CREATE TABLE "webhook_deliveries" (
  "id"             uuid           PRIMARY KEY DEFAULT gen_random_uuid(),
  "webhook_id"     uuid           NOT NULL,
  "event_id"       uuid           NOT NULL,
  "event_type"     text           NOT NULL,
  "payload"        jsonb          NOT NULL,
  "status_code"    integer,
  "attempt"        integer        NOT NULL DEFAULT 1,
  "delivered_at"   timestamptz(6) NOT NULL DEFAULT now(),
  "response_body"  text,
  CONSTRAINT "webhook_deliveries_webhook_id_fkey"
    FOREIGN KEY ("webhook_id") REFERENCES "webhooks"("id")
    ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX "webhook_deliveries_webhook_id_delivered_at_idx"
  ON "webhook_deliveries" ("webhook_id", "delivered_at" DESC);
CREATE INDEX "webhook_deliveries_event_id_idx"
  ON "webhook_deliveries" ("event_id");

-- ── job_audits ──────────────────────────────────────────────────────────────
-- `from_status` / `to_status` reuse the existing "JobStatus" enum created by
-- the initial prisma migration.
CREATE TABLE "job_audits" (
  "id"           uuid           PRIMARY KEY DEFAULT gen_random_uuid(),
  "job_id"       uuid           NOT NULL,
  "from_status"  "JobStatus",
  "to_status"    "JobStatus"    NOT NULL,
  "reason"       text,
  "actor"        text           NOT NULL,
  "created_at"   timestamptz(6) NOT NULL DEFAULT now(),
  CONSTRAINT "job_audits_job_id_fkey"
    FOREIGN KEY ("job_id") REFERENCES "jobs"("id")
    ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX "job_audits_job_id_created_at_idx"
  ON "job_audits" ("job_id", "created_at" DESC);

-- ── idempotency_keys ────────────────────────────────────────────────────────
-- `key` is a cuid supplied by the client (Idempotency-Key header). Scope
-- namespaces the key to an endpoint + tenant, e.g. "seeds:consume:org_<uuid>".
CREATE TABLE "idempotency_keys" (
  "key"            text           PRIMARY KEY,
  "scope"          text           NOT NULL,
  "response_json"  jsonb          NOT NULL,
  "expires_at"     timestamptz(6) NOT NULL,
  "created_at"     timestamptz(6) NOT NULL DEFAULT now()
);

CREATE INDEX "idempotency_keys_expires_at_idx"
  ON "idempotency_keys" ("expires_at");
CREATE INDEX "idempotency_keys_scope_idx"
  ON "idempotency_keys" ("scope");

-- ── Row-Level Security ──────────────────────────────────────────────────────
-- Webhooks: tenant isolation by org membership (same pattern as other
-- org-scoped tables). The app_current_user() helper is defined by the initial
-- enable_rls migration.

ALTER TABLE "webhooks" ENABLE ROW LEVEL SECURITY;
CREATE POLICY webhooks_tenant_isolation ON "webhooks"
  USING (org_id IN (
    SELECT org_id FROM org_members WHERE user_id = app_current_user()
  ));

-- Webhook deliveries: access gated by the parent webhook's RLS. A row is
-- visible iff the caller can see the referenced webhook.
ALTER TABLE "webhook_deliveries" ENABLE ROW LEVEL SECURITY;
CREATE POLICY webhook_deliveries_parent_visibility ON "webhook_deliveries"
  USING (webhook_id IN (
    SELECT id FROM webhooks WHERE org_id IN (
      SELECT org_id FROM org_members WHERE user_id = app_current_user()
    )
  ));

-- Job audits: access gated by the parent job's RLS.
ALTER TABLE "job_audits" ENABLE ROW LEVEL SECURITY;
CREATE POLICY job_audits_parent_visibility ON "job_audits"
  USING (job_id IN (
    SELECT id FROM jobs WHERE org_id IN (
      SELECT org_id FROM org_members WHERE user_id = app_current_user()
    )
  ));

-- Idempotency keys: scope embeds the org id as "<endpoint>:org_<uuid>".
-- Policy extracts the trailing uuid from `scope` and checks membership.
-- The substring pattern matches exactly the producer format in the API.
ALTER TABLE "idempotency_keys" ENABLE ROW LEVEL SECURITY;
CREATE POLICY idempotency_keys_tenant_isolation ON "idempotency_keys"
  USING (
    CASE
      WHEN scope ~ ':org_[0-9a-f-]{36}$'
      THEN substring(scope FROM ':org_([0-9a-f-]{36})$')::uuid IN (
        SELECT org_id FROM org_members WHERE user_id = app_current_user()
      )
      ELSE false
    END
  );
