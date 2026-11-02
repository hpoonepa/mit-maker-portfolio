-- Paper Crane — Wave 14 chat integrations (Slack + Discord)
--
-- Adds two tables and one enum that back per-org outbound notifications to
-- chat platforms via incoming-webhook URLs:
--   1. integrations          — one row per (org, kind) connection
--   2. integration_channels  — one or more channels per integration with
--                              per-channel event filters and mute toggle
--
-- We deliberately keep the schema small:
--   * Only Slack + Discord today; the enum makes future kinds explicit.
--   * `webhook_url` is plaintext for now. Slack/Discord incoming webhook
--     URLs are bearer-style — leak == post-spam, not data exfil — so the
--     blast radius of plaintext storage is acceptable for the MVP. A
--     follow-up migration will wrap these in KMS or store hashes + ID.
--   * `events` is a text[] subset of the integration event registry (see
--     `apps/worker/src/integrations/router.ts`). It is *separate* from the
--     public `webhooks.events[]` registry; chat integrations have a
--     different default mix (e.g. design.created defaults OFF, billing
--     events default ON).
--
-- RLS
--   Both tables are org-scoped. The standard `org_member` policy applies:
--   visibility + mutation gated by membership in the row's org_id.

-- ── Enum ───────────────────────────────────────────────────────────────────

CREATE TYPE "IntegrationKind" AS ENUM ('slack', 'discord');

-- ── integrations ───────────────────────────────────────────────────────────

CREATE TABLE "integrations" (
  "id"         uuid              PRIMARY KEY DEFAULT gen_random_uuid(),
  "org_id"     uuid              NOT NULL,
  "kind"       "IntegrationKind" NOT NULL,
  "name"       text              NOT NULL DEFAULT '',
  "created_at" timestamptz(6)    NOT NULL DEFAULT now(),
  "updated_at" timestamptz(6)    NOT NULL DEFAULT now(),
  CONSTRAINT "integrations_org_id_fkey"
    FOREIGN KEY ("org_id") REFERENCES "organizations"("id")
    ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX "integrations_org_id_created_at_idx"
  ON "integrations" ("org_id", "created_at" DESC);
CREATE INDEX "integrations_org_id_kind_idx"
  ON "integrations" ("org_id", "kind");

-- ── integration_channels ───────────────────────────────────────────────────

CREATE TABLE "integration_channels" (
  "id"               uuid           PRIMARY KEY DEFAULT gen_random_uuid(),
  "integration_id"   uuid           NOT NULL,
  "webhook_url"      text           NOT NULL,
  "events"           text[]         NOT NULL DEFAULT '{}'::text[],
  "muted"            boolean        NOT NULL DEFAULT false,
  "cap_warning_pct"  int            NOT NULL DEFAULT 80,
  "last_delivered_at" timestamptz(6),
  "last_status_code"  int,
  "failure_count"    int            NOT NULL DEFAULT 0,
  "created_at"       timestamptz(6) NOT NULL DEFAULT now(),
  "updated_at"       timestamptz(6) NOT NULL DEFAULT now(),
  CONSTRAINT "integration_channels_integration_id_fkey"
    FOREIGN KEY ("integration_id") REFERENCES "integrations"("id")
    ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX "integration_channels_integration_id_created_at_idx"
  ON "integration_channels" ("integration_id", "created_at" DESC);
CREATE INDEX "integration_channels_muted_idx"
  ON "integration_channels" ("muted");

-- ── RLS ────────────────────────────────────────────────────────────────────
-- Depends on `app_current_user()` and the standard `org_members` join.
-- Pattern matches `webhooks` from the init migration.

ALTER TABLE "integrations" ENABLE ROW LEVEL SECURITY;

CREATE POLICY integrations_org_visibility ON "integrations"
  USING (
    EXISTS (
      SELECT 1 FROM "org_members" m
      WHERE m.org_id = "integrations".org_id
        AND m.user_id = app_current_user()
    )
  );

CREATE POLICY integrations_org_mutation ON "integrations"
  FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM "org_members" m
      WHERE m.org_id = "integrations".org_id
        AND m.user_id = app_current_user()
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM "org_members" m
      WHERE m.org_id = "integrations".org_id
        AND m.user_id = app_current_user()
    )
  );

ALTER TABLE "integration_channels" ENABLE ROW LEVEL SECURITY;

CREATE POLICY integration_channels_org_visibility ON "integration_channels"
  USING (
    EXISTS (
      SELECT 1
        FROM "integrations" i
        JOIN "org_members" m ON m.org_id = i.org_id
       WHERE i.id = "integration_channels".integration_id
         AND m.user_id = app_current_user()
    )
  );

CREATE POLICY integration_channels_org_mutation ON "integration_channels"
  FOR ALL
  USING (
    EXISTS (
      SELECT 1
        FROM "integrations" i
        JOIN "org_members" m ON m.org_id = i.org_id
       WHERE i.id = "integration_channels".integration_id
         AND m.user_id = app_current_user()
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1
        FROM "integrations" i
        JOIN "org_members" m ON m.org_id = i.org_id
       WHERE i.id = "integration_channels".integration_id
         AND m.user_id = app_current_user()
    )
  );
