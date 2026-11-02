-- Paper Crane — FeatureFlag.onCap
--
-- Adds a policy knob to the per-org feature_flags table that governs what
-- happens when a tenant crosses its monthly seed cap:
--
--   block    → reject further job submissions until renewal (default)
--   overage  → allow overage, billed via Stripe metered item downstream
--
-- Keeping this on the feature_flags row lets ops override per-org without a
-- schema change (e.g. flip a strategic customer to overage ahead of a PO).

-- ── Enum ────────────────────────────────────────────────────────────────────
CREATE TYPE "OnCapBehavior" AS ENUM ('block', 'overage');

-- ── Column ──────────────────────────────────────────────────────────────────
-- Default `block` matches the conservative plan 05 default (no surprise
-- billing). Existing rows get the default via NOT NULL + DEFAULT.
ALTER TABLE "feature_flags"
  ADD COLUMN "on_cap" "OnCapBehavior" NOT NULL DEFAULT 'block';
