-- Paper Crane — Wave 12 index audit (idempotent, additive only).
--
-- Audit findings:
--   * Job.target_id is a foreign key with no covering index (sequential scan
--     on every "list jobs for this target" query).
--   * Job.tool is queried frequently in tool-leaderboard and per-tool quota
--     reporting paths but had no index.
--   * Job.project_id is a foreign key with no covering index (cascade-delete
--     on Project.delete walks all jobs sequentially otherwise).
--   * AuditLog (org_id, action, created_at) is the natural shape for the
--     "filter by action within org, newest first" admin query, but only
--     (org_id, created_at) and (action) existed individually.
--   * UsageSeed (org_id, reason, created_at) is needed for billing reports
--     that bucket consumption by reason within a period.
--   * Subscription.stripe_overage_item_id is looked up by Stripe-webhook
--     processors when reconciling overage records.
--   * WebhookDelivery (event_id) exists; we additionally want (event_type,
--     delivered_at) for reliability dashboards.
--
-- All indexes use IF NOT EXISTS so this is safe on baselined production DBs.

CREATE INDEX IF NOT EXISTS "jobs_target_id_idx"
  ON "jobs" ("target_id");

CREATE INDEX IF NOT EXISTS "jobs_project_id_idx"
  ON "jobs" ("project_id");

CREATE INDEX IF NOT EXISTS "jobs_tool_idx"
  ON "jobs" ("tool");

CREATE INDEX IF NOT EXISTS "jobs_org_tool_submitted_idx"
  ON "jobs" ("org_id", "tool", "submitted_at" DESC);

CREATE INDEX IF NOT EXISTS "audit_logs_org_action_created_idx"
  ON "audit_logs" ("org_id", "action", "created_at" DESC);

CREATE INDEX IF NOT EXISTS "usage_seeds_org_reason_created_idx"
  ON "usage_seeds" ("org_id", "reason", "created_at" DESC);

CREATE INDEX IF NOT EXISTS "subscriptions_stripe_overage_item_idx"
  ON "subscriptions" ("stripe_overage_item_id")
  WHERE "stripe_overage_item_id" IS NOT NULL;

CREATE INDEX IF NOT EXISTS "webhook_deliveries_event_type_delivered_idx"
  ON "webhook_deliveries" ("event_type", "delivered_at" DESC);

CREATE INDEX IF NOT EXISTS "notifications_org_user_read_idx"
  ON "notifications" ("org_id", "user_id", "read_at");

CREATE INDEX IF NOT EXISTS "designs_org_rank_idx"
  ON "designs" ("org_id", "rank")
  WHERE "rank" IS NOT NULL;

CREATE INDEX IF NOT EXISTS "targets_pdb_id_idx"
  ON "targets" ("pdb_id")
  WHERE "pdb_id" IS NOT NULL;

CREATE INDEX IF NOT EXISTS "invites_email_idx"
  ON "invites" ("email");

CREATE INDEX IF NOT EXISTS "api_keys_org_active_idx"
  ON "api_keys" ("org_id")
  WHERE "revoked_at" IS NULL;
