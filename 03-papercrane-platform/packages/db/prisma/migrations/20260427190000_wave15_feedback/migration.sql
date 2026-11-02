-- Paper Crane — Wave 15: feedback widget
--
-- Stores beta-tester feedback submitted via the floating "?" button in the
-- dashboard. Both org_id and user_id are nullable so the widget can also
-- accept submissions from anonymous / pre-login flows in the future.
--
-- RLS
--   The feedback table is *append-mostly* and is read by app-server code,
--   never by browser SQL clients. We still enable RLS as defence in depth:
--   org members can SELECT their own org's rows; super-admin lookups go
--   through service-role connections that bypass RLS.

-- ── enum ───────────────────────────────────────────────────────────────────

CREATE TYPE "FeedbackCategory" AS ENUM ('bug', 'feature', 'improvement', 'praise', 'other');

-- ── table ──────────────────────────────────────────────────────────────────

CREATE TABLE "feedback" (
  "id"             text                   PRIMARY KEY,
  "org_id"         uuid,
  "user_id"        uuid,
  "category"       "FeedbackCategory"     NOT NULL DEFAULT 'other',
  "rating"         integer,
  "body"           text                   NOT NULL,
  "page_url"       text,
  "user_agent"     text,
  "screenshot_key" text,
  "metadata"       jsonb,
  "status"         text                   NOT NULL DEFAULT 'new',
  "created_at"     timestamptz(6)         NOT NULL DEFAULT now(),
  CONSTRAINT "feedback_org_id_fkey"
    FOREIGN KEY ("org_id") REFERENCES "organizations"("id")
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT "feedback_user_id_fkey"
    FOREIGN KEY ("user_id") REFERENCES "users"("id")
    ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE INDEX "feedback_status_created_at_idx"
  ON "feedback" ("status", "created_at" DESC);
CREATE INDEX "feedback_org_id_idx"
  ON "feedback" ("org_id");

-- ── RLS ────────────────────────────────────────────────────────────────────

ALTER TABLE "feedback" ENABLE ROW LEVEL SECURITY;

-- Org members read their own org's feedback.
CREATE POLICY "feedback_select_own_org" ON "feedback"
  FOR SELECT
  USING (
    "org_id" IS NOT NULL
    AND "org_id" = app_current_org()
  );

-- Anyone authenticated may insert feedback for their own (user, org) tuple.
-- Anonymous (NULL user) inserts are rejected at this layer; the API server
-- bypasses RLS via service role and decides whether to honour them.
CREATE POLICY "feedback_insert_self" ON "feedback"
  FOR INSERT
  WITH CHECK (
    "user_id" IS NOT NULL
    AND "user_id" = app_current_user()
  );
