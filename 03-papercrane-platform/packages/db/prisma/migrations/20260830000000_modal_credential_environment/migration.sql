-- Modal credentials select a workspace; the optional environment selects the
-- isolated resource namespace used by `modal run` inside that workspace.
ALTER TABLE modal_credentials
  ADD COLUMN IF NOT EXISTS environment TEXT NOT NULL DEFAULT '';
