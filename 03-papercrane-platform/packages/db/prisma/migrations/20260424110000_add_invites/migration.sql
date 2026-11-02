-- Paper Crane — Organization invites
--
-- Adds the `invites` table that powers the "invite by email" flow. An invite
-- is created by an owner/admin (RBAC enforced at the tRPC layer), emailed to
-- the recipient with a one-time `token`, and consumed by
-- `members.acceptInvite` which upserts an `org_members` row for the now-
-- authenticated Supabase user.
--
-- Invariants:
--   * `token` is opaque, URL-safe, and globally unique
--   * An email can only have ONE pending invite per org at a time (enforced
--     by the partial unique index `invites_org_email_pending_unique`)
--   * Accepted invites stay on the table so the audit trail survives; the
--     uniqueness constraint only pins *pending* rows
--   * RLS: org members see invites for their own orgs; creation/mutation is
--     policed at the application layer (tRPC) which already checks role
--
-- Email normalisation uses the `citext` extension (see enable_rls migration
-- style) so `alice@lab.bio` and `Alice@LAB.BIO` collide naturally. The
-- extension is created idempotently here for safety — the initial RLS
-- migration may or may not have enabled it depending on when it shipped.

CREATE EXTENSION IF NOT EXISTS "citext";

-- ── invites ────────────────────────────────────────────────────────────────
CREATE TABLE "invites" (
  "id"           uuid           PRIMARY KEY DEFAULT gen_random_uuid(),
  "org_id"       uuid           NOT NULL,
  "email"        citext         NOT NULL,
  "role"         "OrgRole"      NOT NULL DEFAULT 'member',
  "invited_by"   uuid           NOT NULL,
  "token"        text           NOT NULL,
  "expires_at"   timestamptz(6) NOT NULL,
  "accepted_at"  timestamptz(6),
  "created_at"   timestamptz(6) NOT NULL DEFAULT now(),
  CONSTRAINT "invites_org_id_fkey"
    FOREIGN KEY ("org_id") REFERENCES "organizations"("id")
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT "invites_invited_by_fkey"
    FOREIGN KEY ("invited_by") REFERENCES "users"("id")
    ON DELETE RESTRICT ON UPDATE CASCADE
);

-- `token` is always queried on acceptInvite; a b-tree unique covers both the
-- uniqueness constraint and the lookup.
CREATE UNIQUE INDEX "invites_token_key" ON "invites" ("token");

-- List pending invites for an org (PendingInvitesTable query).
CREATE INDEX "invites_org_id_created_at_idx"
  ON "invites" ("org_id", "created_at" DESC);

-- Expiry sweeper — cheap filter for the cleanup job.
CREATE INDEX "invites_expires_at_idx"
  ON "invites" ("expires_at") WHERE "accepted_at" IS NULL;

-- Exactly-one-pending-invite-per-(org, email) rule. Accepted rows fall out
-- of this partial unique so repeat invites after acceptance are allowed.
CREATE UNIQUE INDEX "invites_org_email_pending_unique"
  ON "invites" ("org_id", "email") WHERE "accepted_at" IS NULL;

-- ── Row-Level Security ──────────────────────────────────────────────────────
-- Visibility: an org member can see invites scoped to their org. This lets
-- the dashboard render pending invites without an API hop. The tRPC layer
-- adds the role check for mutating operations (invite/revoke/accept).
ALTER TABLE "invites" ENABLE ROW LEVEL SECURITY;

CREATE POLICY invites_tenant_isolation ON "invites"
  USING (org_id IN (
    SELECT org_id FROM org_members WHERE user_id = app_current_user()
  ));

-- Acceptance path: the invitee may not yet be a member of the target org
-- when they open /invite/[token]. Allow a SELECT by token for any signed-in
-- user; the tRPC procedure still re-verifies the token + expiry + email.
-- The policy is scoped to SELECT only; writes still go through the service
-- role / RLS-bypass connection used by the API.
CREATE POLICY invites_token_lookup ON "invites"
  FOR SELECT
  USING (app_current_user() IS NOT NULL);
