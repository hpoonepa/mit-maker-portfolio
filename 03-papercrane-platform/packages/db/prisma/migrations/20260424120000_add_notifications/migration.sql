-- Paper Crane — Notifications + preferences
--
-- Adds two tables and two enums for the in-app notification center:
--   1. notifications              — per-user, per-org inbox rows
--   2. notification_preferences   — per-user (category × channel) toggles
--
-- RLS
--   Notifications are user-scoped, not org-scoped (every row lists a
--   recipient user). The policy keys off `app_current_user()` directly —
--   a caller can only see their own rows regardless of which org they
--   are currently acting on behalf of.
--
-- Realtime
--   The Paper Crane dashboard subscribes to this table via
--   `@supabase/supabase-js` realtime. For UPDATE events to carry the old
--   row we set `REPLICA IDENTITY FULL`, and we add the table to the
--   `supabase_realtime` publication. The browser client only receives
--   rows the RLS policy permits, so `filter=user_id=eq.<uid>` is defense
--   in depth, not primary access control.

-- ── Enums ──────────────────────────────────────────────────────────────────

CREATE TYPE "NotificationCategory" AS ENUM ('job', 'billing', 'webhook', 'invite', 'system');
CREATE TYPE "NotificationChannel"  AS ENUM ('in_app', 'email');

-- ── notifications ──────────────────────────────────────────────────────────

CREATE TABLE "notifications" (
  "id"          uuid                    PRIMARY KEY DEFAULT gen_random_uuid(),
  "org_id"      uuid                    NOT NULL,
  "user_id"     uuid                    NOT NULL,
  "category"    "NotificationCategory"  NOT NULL,
  "title"       text                    NOT NULL,
  "description" text,
  "action_url"  text,
  "metadata"    jsonb                   NOT NULL DEFAULT '{}'::jsonb,
  "read_at"     timestamptz(6),
  "created_at"  timestamptz(6)          NOT NULL DEFAULT now(),
  CONSTRAINT "notifications_org_id_fkey"
    FOREIGN KEY ("org_id") REFERENCES "organizations"("id")
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT "notifications_user_id_fkey"
    FOREIGN KEY ("user_id") REFERENCES "users"("id")
    ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX "notifications_user_id_created_at_idx"
  ON "notifications" ("user_id", "created_at" DESC);
CREATE INDEX "notifications_user_id_read_at_idx"
  ON "notifications" ("user_id", "read_at");
CREATE INDEX "notifications_org_id_created_at_idx"
  ON "notifications" ("org_id", "created_at" DESC);

-- ── notification_preferences ───────────────────────────────────────────────

CREATE TABLE "notification_preferences" (
  "user_id"    uuid                    NOT NULL,
  "category"   "NotificationCategory"  NOT NULL,
  "channel"    "NotificationChannel"   NOT NULL,
  "enabled"    boolean                 NOT NULL DEFAULT true,
  "updated_at" timestamptz(6)          NOT NULL DEFAULT now(),
  CONSTRAINT "notification_preferences_pkey"
    PRIMARY KEY ("user_id", "category", "channel"),
  CONSTRAINT "notification_preferences_user_id_fkey"
    FOREIGN KEY ("user_id") REFERENCES "users"("id")
    ON DELETE CASCADE ON UPDATE CASCADE
);

-- ── RLS ────────────────────────────────────────────────────────────────────
-- Depends on `app_current_user()` from the base enable_rls migration.

ALTER TABLE "notifications" ENABLE ROW LEVEL SECURITY;
CREATE POLICY notifications_self_visibility ON "notifications"
  USING (user_id = app_current_user());
CREATE POLICY notifications_self_insert ON "notifications"
  FOR INSERT WITH CHECK (user_id = app_current_user());
CREATE POLICY notifications_self_update ON "notifications"
  FOR UPDATE USING (user_id = app_current_user());

ALTER TABLE "notification_preferences" ENABLE ROW LEVEL SECURITY;
CREATE POLICY notification_preferences_self_visibility ON "notification_preferences"
  USING (user_id = app_current_user());
CREATE POLICY notification_preferences_self_mutation ON "notification_preferences"
  FOR ALL USING (user_id = app_current_user())
  WITH CHECK (user_id = app_current_user());

-- ── Realtime publication ───────────────────────────────────────────────────
-- Add `notifications` to the Supabase realtime publication so the browser
-- client receives INSERT/UPDATE/DELETE events over the websocket. Guarded
-- by the existence check — in non-Supabase Postgres the publication is
-- absent and we silently skip.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime'
  ) THEN
    EXECUTE 'ALTER PUBLICATION supabase_realtime ADD TABLE "notifications"';
  END IF;
END
$$;

-- REPLICA IDENTITY FULL emits the full row on UPDATE/DELETE events so the
-- client can diff old vs new (useful for "marked read" signals).
ALTER TABLE "notifications" REPLICA IDENTITY FULL;
