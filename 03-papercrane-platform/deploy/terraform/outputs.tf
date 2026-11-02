###############################################################################
# Outputs — consumed by GitHub Actions to sync secrets into Vercel + Fly.
# All sensitive outputs are marked sensitive=true; use `terraform output -json`
# in CI and never print them.
###############################################################################

# ---- Supabase (values come from locals since TF provider is limited) ----
output "supabase_project_ref" {
  value       = local.supabase_project_ref
  description = "Supabase project reference id."
}

output "supabase_url" {
  value       = local.supabase_url
  description = "Supabase project URL (https://<ref>.supabase.co)."
}

output "supabase_database_url" {
  value       = local.database_url_direct
  description = "Direct Postgres connection string (use for migrations)."
  sensitive   = true
}

output "supabase_database_url_pooler" {
  value       = local.database_url_pooler
  description = "Pooled Postgres connection string (use for the API/Worker)."
  sensitive   = true
}

# ---- Cloudflare R2 ----
output "r2_bucket_name" {
  value       = cloudflare_r2_bucket.artifacts.name
  description = "R2 bucket name."
}

output "r2_endpoint" {
  value       = "https://${var.cloudflare_account_id}.r2.cloudflarestorage.com"
  description = "S3-compatible R2 endpoint."
}

output "r2_api_token" {
  value       = cloudflare_api_token.r2_rw.value
  description = "R2 API token (bucket-scoped, R/W)."
  sensitive   = true
}

# ---- Upstash ----
output "upstash_redis_queue_url" {
  value       = "rediss://default:${upstash_redis_database.queue.password}@${upstash_redis_database.queue.endpoint}:${upstash_redis_database.queue.port}"
  description = "BullMQ Redis URL (rediss://)."
  sensitive   = true
}

output "upstash_redis_queue_rest_url" {
  value       = "https://${upstash_redis_database.queue.endpoint}"
  description = "Upstash REST URL (for edge / serverless rate-limiting)."
}

output "upstash_redis_queue_rest_token" {
  value       = upstash_redis_database.queue.rest_token
  description = "Upstash REST read/write token."
  sensitive   = true
}

output "upstash_redis_cache_url" {
  value = (
    length(upstash_redis_database.cache) > 0
    ? "rediss://default:${upstash_redis_database.cache[0].password}@${upstash_redis_database.cache[0].endpoint}:${upstash_redis_database.cache[0].port}"
    : ""
  )
  description = "Optional cache Redis URL."
  sensitive   = true
}

# ---- Convenience: rollup consumed by deploy scripts ----
output "secret_bundle" {
  description = "Flattened, sensitive bundle of all secrets for CI injection."
  sensitive   = true
  value = {
    SUPABASE_URL            = local.supabase_url
    SUPABASE_PROJECT_REF    = local.supabase_project_ref
    DATABASE_URL            = local.database_url_pooler
    DIRECT_URL              = local.database_url_direct
    REDIS_URL               = "rediss://default:${upstash_redis_database.queue.password}@${upstash_redis_database.queue.endpoint}:${upstash_redis_database.queue.port}"
    UPSTASH_REDIS_REST_URL  = "https://${upstash_redis_database.queue.endpoint}"
    UPSTASH_REDIS_REST_TOKEN = upstash_redis_database.queue.rest_token
    R2_ENDPOINT             = "https://${var.cloudflare_account_id}.r2.cloudflarestorage.com"
    R2_BUCKET               = cloudflare_r2_bucket.artifacts.name
    R2_API_TOKEN            = cloudflare_api_token.r2_rw.value
  }
}
