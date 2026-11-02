###############################################################################
# Upstash — Redis (BullMQ + rate-limit + ephemeral cache)
###############################################################################

terraform {
  required_providers {
    upstash = {
      source  = "upstash/upstash"
      version = "~> 1.5"
    }
  }
}

provider "upstash" {
  email   = var.upstash_email
  api_key = var.upstash_api_key
}

# ---- Redis: job queues + rate limiting ----
resource "upstash_redis_database" "queue" {
  database_name = "${var.project_name}-queue-${var.environment}"
  region        = var.upstash_redis_region
  tls           = true
  eviction      = true
  multizone     = var.environment == "production"
}

# ---- Optional second DB for caching if you want isolation ----
resource "upstash_redis_database" "cache" {
  count         = var.environment == "production" ? 1 : 0
  database_name = "${var.project_name}-cache-${var.environment}"
  region        = var.upstash_redis_region
  tls           = true
  eviction      = true
  multizone     = true
}
