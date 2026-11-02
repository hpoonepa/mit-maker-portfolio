-- Resumable worker attempts and stale-job detection.
ALTER TABLE "jobs"
  ADD COLUMN "queue_tier" TEXT NOT NULL DEFAULT 'pro',
  ADD COLUMN "attempt" INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN "heartbeat_at" TIMESTAMPTZ(6);

CREATE INDEX "jobs_status_heartbeat_at_idx"
  ON "jobs"("status", "heartbeat_at");
