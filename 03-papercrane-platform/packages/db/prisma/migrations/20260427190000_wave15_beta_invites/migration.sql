-- Paper Crane — Wave 15: beta invite codes + per-user changelog cursor
--
-- Adds:
--   1. users.last_changelog_seen           — text cursor read by WhatsNew modal
--   2. beta_invites                        — invite-code gate for /signup
--
-- Concurrency
-- -----------
-- The usedCount increment in `beta.validateInvite` runs as
--     UPDATE beta_invites
--        SET used_count = used_count + 1
--      WHERE code = $1
--        AND (max_uses = 0 OR used_count < max_uses)
--        AND (expires_at IS NULL OR expires_at > now());
-- which the unique-constraint + atomic UPDATE makes safe under contention:
-- racing claimers either both succeed (multi-use cap not hit) or one of
-- them fails the WHERE and gets `usesRemaining: 0`.
--
-- RLS
-- ---
-- `beta_invites` is admin-only. Service role bypasses; the tRPC router
-- enforces the `admin`/`owner` role check at the application layer.

-- ── users.last_changelog_seen ──────────────────────────────────────────────
ALTER TABLE "users"
  ADD COLUMN "last_changelog_seen" text;

-- ── beta_invites ───────────────────────────────────────────────────────────
CREATE TABLE "beta_invites" (
  "id"               text                   PRIMARY KEY,
  "code"             text                   NOT NULL,
  "max_uses"         integer                NOT NULL DEFAULT 1,
  "used_count"       integer                NOT NULL DEFAULT 0,
  "expires_at"       timestamptz(6),
  "note"             text,
  "generated_by"     uuid,
  "used_by_user_id"  uuid,
  "created_at"       timestamptz(6)         NOT NULL DEFAULT now(),
  CONSTRAINT "beta_invites_generated_by_fkey"
    FOREIGN KEY ("generated_by")    REFERENCES "users"("id")
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT "beta_invites_used_by_user_id_fkey"
    FOREIGN KEY ("used_by_user_id") REFERENCES "users"("id")
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT "beta_invites_max_uses_nonneg" CHECK ("max_uses" >= 0),
  CONSTRAINT "beta_invites_used_count_nonneg" CHECK ("used_count" >= 0)
);

CREATE UNIQUE INDEX "beta_invites_code_key"
  ON "beta_invites" ("code");

CREATE INDEX "beta_invites_generated_by_created_at_idx"
  ON "beta_invites" ("generated_by", "created_at" DESC);

CREATE INDEX "beta_invites_expires_at_idx"
  ON "beta_invites" ("expires_at");

-- RLS — service role bypasses; deny-by-default for everyone else. The tRPC
-- router validates the caller's role *before* it reaches the table.
ALTER TABLE "beta_invites" ENABLE ROW LEVEL SECURITY;

CREATE POLICY "beta_invites_service_role_all"
  ON "beta_invites" FOR ALL
  USING (current_setting('role', true) = 'service_role')
  WITH CHECK (current_setting('role', true) = 'service_role');
