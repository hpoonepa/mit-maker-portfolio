-- Durable, idempotent admission for the private beta.
-- A Supabase identity is not considered admitted until a beta invite claim
-- records this timestamp. Existing beta testers are backfilled from an invite
-- they previously claimed through `used_by_user_id`.

ALTER TABLE "users"
  ADD COLUMN "beta_access_granted_at" TIMESTAMPTZ(6);

UPDATE "users" AS u
   SET "beta_access_granted_at" = CURRENT_TIMESTAMP
 WHERE EXISTS (
   SELECT 1
     FROM "beta_invites" AS bi
    WHERE bi."used_by_user_id" = u."id"
 );

CREATE INDEX "users_beta_access_granted_at_idx"
  ON "users" ("beta_access_granted_at")
  WHERE "beta_access_granted_at" IS NOT NULL;
