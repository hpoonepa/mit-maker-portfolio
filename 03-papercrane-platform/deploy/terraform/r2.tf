###############################################################################
# Cloudflare R2 — object storage for Paper Crane artifacts
###############################################################################

terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.40"
    }
  }
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# ---- Primary artifacts bucket ----
resource "cloudflare_r2_bucket" "artifacts" {
  account_id = var.cloudflare_account_id
  name       = var.r2_bucket_name
  location   = var.r2_bucket_location
}

# ---- Lifecycle: retain logs 90d, artifacts 365d ----
# Cloudflare's TF provider exposes lifecycle via cloudflare_r2_bucket_lifecycle
# on v4.40+. If not yet on that version, apply via wrangler: `wrangler r2 bucket
# lifecycle put papercrane-artifacts --config deploy/r2-lifecycle.json`.
resource "cloudflare_r2_bucket_lifecycle" "artifacts" {
  account_id = var.cloudflare_account_id
  bucket     = cloudflare_r2_bucket.artifacts.name

  rule {
    id     = "expire-job-logs"
    status = "Enabled"
    filter {
      prefix = "logs/"
    }
    expiration {
      days = 90
    }
  }

  rule {
    id     = "expire-artifacts"
    status = "Enabled"
    filter {
      prefix = "artifacts/"
    }
    expiration {
      days = 365
    }
  }
}

# ---- CORS for browser uploads from app.papercrane.bio ----
resource "cloudflare_r2_bucket_cors" "artifacts" {
  account_id = var.cloudflare_account_id
  bucket     = cloudflare_r2_bucket.artifacts.name

  rules {
    allowed_origins = [
      "https://${var.domain}",
      "https://app.${var.domain}",
      "http://localhost:3000",
      "http://localhost:3002",
    ]
    allowed_methods = ["GET", "PUT", "POST", "HEAD"]
    allowed_headers = ["*"]
    expose_headers  = ["ETag", "Content-Length"]
    max_age_seconds = 3600
  }
}

# ---- API token scoped to this bucket (consumed by API + Worker) ----
# NOTE: cloudflare_api_token supports object-storage scopes starting on the
# account-scoped R2 permission group. If your provider version predates that,
# create the token manually in the dashboard and drop it in as a fly secret.
resource "cloudflare_api_token" "r2_rw" {
  name = "${var.project_name}-r2-rw-${var.environment}"

  policy {
    permission_groups = [
      data.cloudflare_api_token_permission_groups.all.permissions["Workers R2 Storage Write"],
      data.cloudflare_api_token_permission_groups.all.permissions["Workers R2 Storage Read"],
    ]
    resources = {
      "com.cloudflare.api.account.${var.cloudflare_account_id}" = "*"
    }
  }
}

data "cloudflare_api_token_permission_groups" "all" {}
