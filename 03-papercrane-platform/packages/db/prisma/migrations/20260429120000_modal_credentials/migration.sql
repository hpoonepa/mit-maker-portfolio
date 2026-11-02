-- Org-scoped Modal credentials for bring-your-own-compute dispatch.
-- The token secret is stored server-side only and is never returned by API
-- responses. A future hardening pass should wrap this value with KMS.

CREATE TABLE IF NOT EXISTS modal_credentials (
  org_id UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
  token_id TEXT NOT NULL,
  token_secret TEXT NOT NULL,
  workspace TEXT NOT NULL DEFAULT '',
  last_validated_at TIMESTAMPTZ,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS modal_credentials_updated_at_idx
  ON modal_credentials(updated_at DESC);

ALTER TABLE modal_credentials ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS modal_credentials_org_select ON modal_credentials;
CREATE POLICY modal_credentials_org_select
  ON modal_credentials
  FOR SELECT
  USING (org_id = app_current_org());

DROP POLICY IF EXISTS modal_credentials_org_write ON modal_credentials;
CREATE POLICY modal_credentials_org_write
  ON modal_credentials
  FOR ALL
  USING (org_id = app_current_org())
  WITH CHECK (org_id = app_current_org());
