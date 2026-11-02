-- Paper Crane — Baseline schema (init).
--
-- Hand-curated from `prisma migrate diff --from-empty --to-schema-datamodel`,
-- with later-added tables, columns, enums, indexes, and constraints removed
-- so this migration represents the schema state as it was when RLS was first
-- introduced. Subsequent migrations layer their additions on top:
--
--   20260423110000_enable_rls                 — RLS bootstrap (renamed from 00000000000000)
--   20260423120000_add_webhook_audit_idempotency
--   20260423130000_add_feature_flag_oncap     — adds feature_flags.on_cap + OnCapBehavior
--   20260424100000_add_audit_log              — adds AuditAction enum + audit_logs
--   20260424110000_add_invites                — adds invites
--   20260424120000_add_notifications          — adds NotificationCategory/Channel + notifications/preferences
--   20260424130000_apikey_rotation            — adds api_keys.{expires_at,rotated_at,grace_expires_at,rotated_from_id} + indexes/checks
--   20260427000000_wave8_onboarding_state     — adds user_onboarding
--   20260427120000_wave9_overage_item_id      — adds subscriptions.stripe_overage_item_id + AuditAction value
--
-- Running `prisma migrate deploy` against an empty Postgres now applies these
-- in lexicographic order with no manual recovery required.

-- ── Extensions ─────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Enums ──────────────────────────────────────────────────────────────────
CREATE TYPE "OrgTier" AS ENUM ('free', 'pro', 'frontier');
CREATE TYPE "OrgRole" AS ENUM ('owner', 'admin', 'member', 'viewer');
CREATE TYPE "JobStatus" AS ENUM ('queued', 'preparing', 'running', 'cancelling', 'cancelled', 'partial', 'succeeded', 'failed', 'purged');
CREATE TYPE "GpuBackend" AS ENUM ('modal', 'vastai', 'vpc');
CREATE TYPE "SubscriptionStatus" AS ENUM ('trialing', 'active', 'past_due', 'canceled', 'incomplete', 'incomplete_expired', 'unpaid', 'paused');
CREATE TYPE "ToolCategory" AS ENUM ('backbone', 'sequence', 'structure', 'ranking', 'utility', 'composite');
CREATE TYPE "ToolTier" AS ENUM ('free', 'pro', 'frontier');
CREATE TYPE "BenchmarkRunStatus" AS ENUM ('pending', 'running', 'succeeded', 'failed');
CREATE TYPE "BenchmarkTrigger" AS ENUM ('nightly', 'weekly', 'on_demand', 'submission', 'rerun');
CREATE TYPE "BenchmarkSubmissionStatus" AS ENUM ('submitted', 'dry_run_passed', 'dry_run_failed', 'approved', 'rejected', 'promoted', 'retired');

-- ── Tables ─────────────────────────────────────────────────────────────────
CREATE TABLE "organizations" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "slug" TEXT NOT NULL,
    "tier" "OrgTier" NOT NULL DEFAULT 'free',
    "seeds_quota" INTEGER NOT NULL DEFAULT 0,
    "seeds_used" INTEGER NOT NULL DEFAULT 0,
    "retention_days" INTEGER NOT NULL DEFAULT 7,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "organizations_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "users" (
    "id" UUID NOT NULL,
    "email" TEXT NOT NULL,
    "name" TEXT,
    "default_org_id" UUID,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "users_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "org_members" (
    "org_id" UUID NOT NULL,
    "user_id" UUID NOT NULL,
    "role" "OrgRole" NOT NULL DEFAULT 'member',
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "org_members_pkey" PRIMARY KEY ("org_id","user_id")
);

CREATE TABLE "projects" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "org_id" UUID NOT NULL,
    "name" TEXT NOT NULL,
    "created_by" UUID,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "projects_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "targets" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "org_id" UUID NOT NULL,
    "project_id" UUID,
    "name" TEXT NOT NULL,
    "pdb_id" TEXT,
    "artifact_key" TEXT NOT NULL,
    "hotspots" JSONB,
    "checksum" TEXT NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "targets_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "jobs" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "org_id" UUID NOT NULL,
    "project_id" UUID,
    "target_id" UUID,
    "tool" TEXT NOT NULL,
    "tool_version" TEXT NOT NULL,
    "params" JSONB NOT NULL,
    "seeds_requested" INTEGER NOT NULL,
    "status" "JobStatus" NOT NULL,
    "gpu_backend" "GpuBackend",
    "seeds_consumed" INTEGER NOT NULL DEFAULT 0,
    "error" JSONB,
    "submitted_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "started_at" TIMESTAMPTZ(6),
    "completed_at" TIMESTAMPTZ(6),
    "expires_at" TIMESTAMPTZ(6) NOT NULL,
    CONSTRAINT "jobs_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "designs" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "job_id" UUID NOT NULL,
    "org_id" UUID NOT NULL,
    "seed" INTEGER NOT NULL,
    "metrics" JSONB NOT NULL,
    "artifact_key" TEXT NOT NULL,
    "rank" INTEGER,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "designs_pkey" PRIMARY KEY ("id")
);

-- Note: rotation columns (expires_at, rotated_at, grace_expires_at,
-- rotated_from_id) are added by 20260424130000_apikey_rotation.
CREATE TABLE "api_keys" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "org_id" UUID NOT NULL,
    "name" TEXT NOT NULL,
    "prefix" TEXT NOT NULL,
    "hash" TEXT NOT NULL,
    "scopes" TEXT[],
    "last_used_at" TIMESTAMPTZ(6),
    "revoked_at" TIMESTAMPTZ(6),
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "api_keys_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "usage_seeds" (
    "id" BIGSERIAL NOT NULL,
    "org_id" UUID NOT NULL,
    "job_id" UUID,
    "seeds" INTEGER NOT NULL,
    "reason" TEXT NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "usage_seeds_pkey" PRIMARY KEY ("id")
);

-- Note: stripe_overage_item_id is added by 20260427120000_wave9_overage_item_id.
CREATE TABLE "subscriptions" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "org_id" UUID NOT NULL,
    "stripe_customer_id" TEXT NOT NULL,
    "stripe_subscription_id" TEXT NOT NULL,
    "status" "SubscriptionStatus" NOT NULL,
    "tier" "OrgTier" NOT NULL,
    "current_period_end" TIMESTAMPTZ(6) NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    CONSTRAINT "subscriptions_pkey" PRIMARY KEY ("id")
);

-- Note: on_cap is added by 20260423130000_add_feature_flag_oncap.
CREATE TABLE "feature_flags" (
    "org_id" UUID NOT NULL,
    "retention_days" INTEGER NOT NULL DEFAULT 7,
    "max_concurrent" INTEGER NOT NULL DEFAULT 2,
    "vpc_enabled" BOOLEAN NOT NULL DEFAULT false,
    "closed_weights_allowed" BOOLEAN NOT NULL DEFAULT false,
    "byoc_required" BOOLEAN NOT NULL DEFAULT false,
    "notes" TEXT,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    CONSTRAINT "feature_flags_pkey" PRIMARY KEY ("org_id")
);

CREATE TABLE "tools" (
    "id" TEXT NOT NULL,
    "display_name" TEXT NOT NULL,
    "version" TEXT NOT NULL,
    "adapter_version" TEXT NOT NULL,
    "category" "ToolCategory" NOT NULL,
    "tier" "ToolTier" NOT NULL DEFAULT 'free',
    "license" TEXT NOT NULL,
    "image" TEXT NOT NULL,
    "image_digest" TEXT NOT NULL,
    "compute" JSONB NOT NULL,
    "input_schema" JSONB NOT NULL,
    "output_schema" JSONB NOT NULL,
    "default_params" JSONB NOT NULL DEFAULT '{}',
    "composes" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "active" BOOLEAN NOT NULL DEFAULT true,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    CONSTRAINT "tools_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "benchmark_runs" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "run_slug" TEXT NOT NULL,
    "benchmark_version" TEXT NOT NULL,
    "tool_id" TEXT NOT NULL,
    "tool_version" TEXT NOT NULL,
    "target_id" TEXT NOT NULL,
    "target_fingerprint" TEXT NOT NULL,
    "config_hash" TEXT NOT NULL,
    "config" JSONB NOT NULL,
    "seed_range_start" INTEGER NOT NULL,
    "seed_range_end" INTEGER NOT NULL,
    "compute" JSONB NOT NULL,
    "container_digest" TEXT NOT NULL,
    "results_digest" TEXT,
    "cost_usd" DECIMAL(10,4),
    "wallclock_sec" INTEGER,
    "status" "BenchmarkRunStatus" NOT NULL DEFAULT 'pending',
    "trigger" "BenchmarkTrigger" NOT NULL,
    "manifest_ipfs_cid" TEXT,
    "manifest_s3_key" TEXT,
    "error" JSONB,
    "started_at" TIMESTAMPTZ(6),
    "completed_at" TIMESTAMPTZ(6),
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "submission_id" UUID,
    CONSTRAINT "benchmark_runs_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "benchmark_submissions" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "tool_name" TEXT NOT NULL,
    "tool_version" TEXT NOT NULL,
    "submitter_email" TEXT NOT NULL,
    "submitter_name" TEXT,
    "pr_url" TEXT NOT NULL,
    "commit_sha" TEXT NOT NULL,
    "install_recipe" JSONB NOT NULL,
    "configs_by_target" JSONB NOT NULL,
    "attestation" JSONB NOT NULL,
    "status" "BenchmarkSubmissionStatus" NOT NULL DEFAULT 'submitted',
    "review_notes" TEXT,
    "approved_by" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "approved_at" TIMESTAMPTZ(6),
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ(6) NOT NULL,
    CONSTRAINT "benchmark_submissions_pkey" PRIMARY KEY ("id")
);

-- ── Indexes ────────────────────────────────────────────────────────────────
CREATE UNIQUE INDEX "organizations_slug_key" ON "organizations"("slug");
CREATE UNIQUE INDEX "users_email_key" ON "users"("email");
CREATE INDEX "org_members_user_id_idx" ON "org_members"("user_id");
CREATE INDEX "projects_org_id_created_at_idx" ON "projects"("org_id", "created_at" DESC);
CREATE INDEX "targets_org_id_created_at_idx" ON "targets"("org_id", "created_at" DESC);
CREATE INDEX "targets_project_id_idx" ON "targets"("project_id");
CREATE INDEX "jobs_org_id_status_submitted_at_idx" ON "jobs"("org_id", "status", "submitted_at" DESC);
CREATE INDEX "jobs_expires_at_idx" ON "jobs"("expires_at");
CREATE INDEX "designs_job_id_rank_idx" ON "designs"("job_id", "rank");
CREATE INDEX "designs_org_id_created_at_idx" ON "designs"("org_id", "created_at" DESC);
CREATE UNIQUE INDEX "designs_job_id_seed_unique" ON "designs"("job_id", "seed");
CREATE INDEX "api_keys_hash_idx" ON "api_keys"("hash");
CREATE INDEX "api_keys_org_id_created_at_idx" ON "api_keys"("org_id", "created_at" DESC);
CREATE INDEX "usage_seeds_org_id_created_at_idx" ON "usage_seeds"("org_id", "created_at" DESC);
CREATE INDEX "usage_seeds_job_id_idx" ON "usage_seeds"("job_id");
CREATE UNIQUE INDEX "subscriptions_org_id_key" ON "subscriptions"("org_id");
CREATE UNIQUE INDEX "subscriptions_stripe_customer_id_key" ON "subscriptions"("stripe_customer_id");
CREATE UNIQUE INDEX "subscriptions_stripe_subscription_id_key" ON "subscriptions"("stripe_subscription_id");
CREATE INDEX "subscriptions_status_idx" ON "subscriptions"("status");
CREATE INDEX "subscriptions_current_period_end_idx" ON "subscriptions"("current_period_end");
CREATE INDEX "tools_category_tier_idx" ON "tools"("category", "tier");
CREATE INDEX "tools_active_idx" ON "tools"("active");
CREATE INDEX "tools_version_idx" ON "tools"("version");
CREATE UNIQUE INDEX "benchmark_runs_run_slug_key" ON "benchmark_runs"("run_slug");
CREATE INDEX "benchmark_runs_tool_id_target_id_benchmark_version_idx" ON "benchmark_runs"("tool_id", "target_id", "benchmark_version");
CREATE INDEX "benchmark_runs_benchmark_version_status_idx" ON "benchmark_runs"("benchmark_version", "status");
CREATE INDEX "benchmark_runs_created_at_idx" ON "benchmark_runs"("created_at" DESC);
CREATE INDEX "benchmark_submissions_status_created_at_idx" ON "benchmark_submissions"("status", "created_at" DESC);
CREATE INDEX "benchmark_submissions_tool_name_tool_version_idx" ON "benchmark_submissions"("tool_name", "tool_version");

-- ── Foreign Keys ───────────────────────────────────────────────────────────
ALTER TABLE "users" ADD CONSTRAINT "users_default_org_id_fkey" FOREIGN KEY ("default_org_id") REFERENCES "organizations"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "org_members" ADD CONSTRAINT "org_members_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "organizations"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "org_members" ADD CONSTRAINT "org_members_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "projects" ADD CONSTRAINT "projects_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "organizations"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "projects" ADD CONSTRAINT "projects_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "users"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "targets" ADD CONSTRAINT "targets_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "organizations"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "targets" ADD CONSTRAINT "targets_project_id_fkey" FOREIGN KEY ("project_id") REFERENCES "projects"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "jobs" ADD CONSTRAINT "jobs_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "organizations"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "jobs" ADD CONSTRAINT "jobs_project_id_fkey" FOREIGN KEY ("project_id") REFERENCES "projects"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "jobs" ADD CONSTRAINT "jobs_target_id_fkey" FOREIGN KEY ("target_id") REFERENCES "targets"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "designs" ADD CONSTRAINT "designs_job_id_fkey" FOREIGN KEY ("job_id") REFERENCES "jobs"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "designs" ADD CONSTRAINT "designs_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "organizations"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "api_keys" ADD CONSTRAINT "api_keys_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "organizations"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "usage_seeds" ADD CONSTRAINT "usage_seeds_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "organizations"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "usage_seeds" ADD CONSTRAINT "usage_seeds_job_id_fkey" FOREIGN KEY ("job_id") REFERENCES "jobs"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "subscriptions" ADD CONSTRAINT "subscriptions_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "organizations"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "feature_flags" ADD CONSTRAINT "feature_flags_org_id_fkey" FOREIGN KEY ("org_id") REFERENCES "organizations"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "benchmark_runs" ADD CONSTRAINT "benchmark_runs_tool_id_fkey" FOREIGN KEY ("tool_id") REFERENCES "tools"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "benchmark_runs" ADD CONSTRAINT "benchmark_runs_submission_id_fkey" FOREIGN KEY ("submission_id") REFERENCES "benchmark_submissions"("id") ON DELETE SET NULL ON UPDATE CASCADE;
