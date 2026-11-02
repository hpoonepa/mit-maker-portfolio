-- Durable, redacted worker event history. Redis/SSE remains the live path;
-- this table backs replay, support diagnostics, and `papercrane jobs logs`.
CREATE TABLE "job_logs" (
  "id"         uuid           PRIMARY KEY DEFAULT gen_random_uuid(),
  "job_id"     uuid           NOT NULL,
  "level"      text           NOT NULL,
  "event"      text           NOT NULL,
  "message"    text           NOT NULL,
  "metadata"   jsonb,
  "created_at" timestamptz(6) NOT NULL DEFAULT now(),
  CONSTRAINT "job_logs_job_id_fkey"
    FOREIGN KEY ("job_id") REFERENCES "jobs"("id")
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT "job_logs_level_check"
    CHECK ("level" IN ('info', 'warn', 'error'))
);

CREATE INDEX "job_logs_job_id_created_at_id_idx"
  ON "job_logs" ("job_id", "created_at", "id");

ALTER TABLE "job_logs" ENABLE ROW LEVEL SECURITY;
CREATE POLICY job_logs_parent_visibility ON "job_logs"
  FOR SELECT
  USING (job_id IN (
    SELECT id FROM jobs WHERE org_id IN (
      SELECT org_id FROM org_members WHERE user_id = app_current_user()
    )
  ));
