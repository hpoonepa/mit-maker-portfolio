-- Paper Crane — Wave 8: onboarding state persistence
--
-- Adds a per-user row tracking where the user is in the onboarding wizard
-- and which persona they picked on the welcome step. The wizard previously
-- only kept this in localStorage, which meant:
--   - users couldn't resume on a different device
--   - the auth middleware had no way to know the user was already mid-flow
--
-- Schema decisions
-- ----------------
--   - Primary key is `user_id` (one onboarding row per user, ever).
--   - `org_id` is nullable: it stays null until the user completes step 2
--     (create-org). For invite-link signups, step 2 is skipped and `org_id`
--     gets backfilled from the invite at step 1.
--   - `persona` is nullable text — we accept the three known personas
--     (`pi`, `grad`, `industry`) and ignore anything else. Constraining
--     this with a Postgres ENUM is overkill for a 3-value set that may
--     change as we learn more about who's signing up.
--   - `current_step` is plain text rather than an enum so the application
--     can introduce new steps via code-only changes.
--   - `completed_at` (nullable timestamptz) doubles as both the "is the user
--     done with onboarding?" boolean and the moment they finished — useful
--     for funnel analytics.
--
-- RLS
--   Onboarding rows are *strictly* user-scoped — a user can only ever see
--   or mutate their own row. The policy keys off `app_current_user()`.

CREATE TABLE "user_onboarding" (
  "user_id"         uuid          PRIMARY KEY,
  "org_id"          uuid,
  "current_step"    text          NOT NULL DEFAULT 'welcome',
  "persona"         text,
  "completed_at"    timestamptz(6),
  "last_updated_at" timestamptz(6) NOT NULL DEFAULT now(),
  CONSTRAINT "user_onboarding_user_id_fkey"
    FOREIGN KEY ("user_id") REFERENCES "users"("id")
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT "user_onboarding_org_id_fkey"
    FOREIGN KEY ("org_id") REFERENCES "organizations"("id")
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT "user_onboarding_persona_check"
    CHECK ("persona" IS NULL OR "persona" IN ('pi', 'grad', 'industry'))
);

CREATE INDEX "user_onboarding_org_id_idx"
  ON "user_onboarding" ("org_id")
  WHERE "org_id" IS NOT NULL;

CREATE INDEX "user_onboarding_completed_at_idx"
  ON "user_onboarding" ("completed_at")
  WHERE "completed_at" IS NOT NULL;

-- ── RLS ────────────────────────────────────────────────────────────────────

ALTER TABLE "user_onboarding" ENABLE ROW LEVEL SECURITY;

CREATE POLICY "user_onboarding_self_select"
  ON "user_onboarding"
  FOR SELECT
  USING ("user_id" = app_current_user());

CREATE POLICY "user_onboarding_self_insert"
  ON "user_onboarding"
  FOR INSERT
  WITH CHECK ("user_id" = app_current_user());

CREATE POLICY "user_onboarding_self_update"
  ON "user_onboarding"
  FOR UPDATE
  USING ("user_id" = app_current_user())
  WITH CHECK ("user_id" = app_current_user());
