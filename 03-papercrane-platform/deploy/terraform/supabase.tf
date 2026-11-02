###############################################################################
# Supabase
###############################################################################
# Supabase does NOT currently ship a first-class Terraform provider. The
# official "supabase/supabase" Terraform provider only covers a narrow slice of
# project management (personal access tokens, branches, functions). Most
# bootstrap operations (create project, set DB password, run migrations,
# configure auth) are still handled via the Supabase CLI + GitHub Action.
#
# Strategy:
#   1. Create the project ONCE via the web console (or `supabase projects create`)
#      and record its `project_ref` in `terraform.tfvars` as supabase_project_ref.
#   2. Use this TF to manage what the provider DOES support: database branches,
#      SQL-level roles via postgresql provider, secrets.
#   3. Migrations live in `packages/db/migrations/*.sql` and are applied via
#      `supabase db push` in .github/workflows/deploy-api.yml before Fly deploy.
#
# See deploy/terraform/README.md for the full bootstrap runbook.
###############################################################################

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    supabase = {
      source  = "supabase/supabase"
      version = "~> 1.0"
    }
  }
}

provider "supabase" {
  # SUPABASE_ACCESS_TOKEN must be exported (personal access token).
  # terraform reads it from env; no fields required here.
}

# Placeholder: reference an existing project created via CLI/console.
# Uncomment once `supabase/supabase` provider exposes a `supabase_project` data source
# matching your provider version.
#
# data "supabase_project" "main" {
#   id = var.supabase_project_ref
# }

# Example branch for preview environments (requires paid Supabase plan).
# resource "supabase_branch" "preview" {
#   count      = var.environment == "preview" ? 1 : 0
#   project_ref = var.supabase_project_ref
#   name        = "preview-${terraform.workspace}"
#   region      = "us-east-1"
# }

# Pooler + direct connection strings are computed here so other modules
# (fly secrets, vercel env) can consume them. Values get filled by humans after
# CLI bootstrap; kept as locals so Terraform stays declarative.
locals {
  supabase_project_ref = var.supabase_project_ref
  supabase_url         = var.supabase_project_ref != "" ? "https://${var.supabase_project_ref}.supabase.co" : ""
  supabase_db_host     = var.supabase_project_ref != "" ? "db.${var.supabase_project_ref}.supabase.co" : ""
  supabase_pooler_host = var.supabase_project_ref != "" ? "aws-0-${var.region}.pooler.supabase.com" : ""
  database_url_direct = (
    var.supabase_project_ref != "" && var.supabase_db_password != ""
    ? "postgresql://postgres:${var.supabase_db_password}@${local.supabase_db_host}:5432/postgres?sslmode=require"
    : ""
  )
  database_url_pooler = (
    var.supabase_project_ref != "" && var.supabase_db_password != ""
    ? "postgresql://postgres.${var.supabase_project_ref}:${var.supabase_db_password}@${local.supabase_pooler_host}:6543/postgres?pgbouncer=true"
    : ""
  )
}
