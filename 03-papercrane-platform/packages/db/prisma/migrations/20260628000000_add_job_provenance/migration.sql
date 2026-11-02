-- Job provenance: persist the resolved adapter version and container image
-- digest on each Job at submit time, alongside the existing tool_version.
--
-- These are captured from the Tool catalog row in the same RLS transaction
-- that inserts the Job, so a published result remains reproducible even after
-- the catalog entry is bumped. Both columns are nullable — jobs submitted
-- before this migration have no recorded adapter/image provenance.
ALTER TABLE "jobs"
  ADD COLUMN IF NOT EXISTS "adapter_version" TEXT,
  ADD COLUMN IF NOT EXISTS "image_digest"    TEXT;
