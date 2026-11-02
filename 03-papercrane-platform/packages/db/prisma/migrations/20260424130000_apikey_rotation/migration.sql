-- Paper Crane — API key rotation (24h grace) + optional expiry.
--
-- Adds to `api_keys`:
--   * expires_at         (optional TTL; null = never)
--   * rotated_at         (NOT NULL on the OLD half of a rotation pair)
--   * grace_expires_at   (NOT NULL on the OLD half; defaults to rotated_at + 24h)
--   * rotated_from_id    (self-FK; NOT NULL on the NEW half, pointing back at the
--                         old row so operators can reconstruct the chain for
--                         audit)
--
-- State machine (derived):
--   active    = revoked_at IS NULL AND rotated_at IS NULL
--               AND (expires_at IS NULL OR expires_at > now())
--   rotating  = revoked_at IS NULL AND rotated_at IS NOT NULL
--               AND grace_expires_at > now()
--   revoked   = revoked_at IS NOT NULL
--   expired   = (expires_at <= now()) OR (rotated_at IS NOT NULL AND grace_expires_at <= now())
--
-- A rotated row MUST NOT itself be re-rotated; the router/UI enforce this via
-- the `canRotate` helper in `apps/app/lib/keys/rotation.ts`.
--
-- The worker cron at apps/worker/src/apiKeyRotation/processor.ts runs the
-- sweep below on its configured interval:
--
--   UPDATE api_keys
--      SET revoked_at = now()
--    WHERE rotated_at IS NOT NULL
--      AND revoked_at IS NULL
--      AND grace_expires_at < now();
--
-- ── Columns ─────────────────────────────────────────────────────────────────
ALTER TABLE "api_keys"
  ADD COLUMN "expires_at"       TIMESTAMPTZ(6),
  ADD COLUMN "rotated_at"       TIMESTAMPTZ(6),
  ADD COLUMN "grace_expires_at" TIMESTAMPTZ(6),
  ADD COLUMN "rotated_from_id"  UUID;

-- ── Self-reference FK ────────────────────────────────────────────────────────
-- ON DELETE SET NULL so purging a parent key (via future retention) does not
-- cascade through the rotation chain. The orphan row is still valid; it just
-- loses its pointer.
ALTER TABLE "api_keys"
  ADD CONSTRAINT "api_keys_rotated_from_id_fkey"
    FOREIGN KEY ("rotated_from_id")
    REFERENCES "api_keys"("id")
    ON DELETE SET NULL
    ON UPDATE CASCADE;

-- ── Invariants ──────────────────────────────────────────────────────────────
-- Either both rotation timestamps are set, or neither is. Prevents a partial
-- write (rotated_at set without grace_expires_at) from ever reaching the
-- sweeper, which would otherwise never revoke that row.
ALTER TABLE "api_keys"
  ADD CONSTRAINT "api_keys_rotation_pair_complete"
    CHECK (
      (rotated_at IS NULL AND grace_expires_at IS NULL)
      OR (rotated_at IS NOT NULL AND grace_expires_at IS NOT NULL)
    );

-- A row cannot be rotated from itself.
ALTER TABLE "api_keys"
  ADD CONSTRAINT "api_keys_no_self_rotation"
    CHECK (rotated_from_id IS NULL OR rotated_from_id <> id);

-- ── Indexes ─────────────────────────────────────────────────────────────────
-- Cleanup sweeper: narrow partial index matches exactly the rows it needs.
-- Tiny (only the in-grace rotated rows live here) → scans are ~instant.
CREATE INDEX "api_keys_grace_sweep_idx"
  ON "api_keys" ("grace_expires_at")
  WHERE rotated_at IS NOT NULL AND revoked_at IS NULL;

-- Rotation chain lookups (audit / history UI).
CREATE INDEX "api_keys_rotated_from_id_idx"
  ON "api_keys" ("rotated_from_id");
