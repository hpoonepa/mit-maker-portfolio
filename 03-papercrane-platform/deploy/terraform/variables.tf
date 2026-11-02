###############################################################################
# Shared variables for Paper Crane infrastructure
###############################################################################

variable "environment" {
  description = "Deployment environment (production | staging | preview)."
  type        = string
  default     = "production"
  validation {
    condition     = contains(["production", "staging", "preview"], var.environment)
    error_message = "environment must be one of: production, staging, preview."
  }
}

variable "project_name" {
  description = "Short name used as a prefix for cloud resources."
  type        = string
  default     = "papercrane"
}

variable "region" {
  description = "Primary region hint for regional resources (Fly, Upstash, R2 jurisdiction)."
  type        = string
  default     = "us-east-1"
}

variable "domain" {
  description = "Root domain for the product, e.g. papercrane.bio."
  type        = string
  default     = "papercrane.bio"
}

# ---- Supabase ----
variable "supabase_project_ref" {
  description = "Supabase project reference (e.g. abcdxyz). Created via CLI, referenced here."
  type        = string
  default     = ""
}

variable "supabase_db_password" {
  description = "Database password for the Supabase project."
  type        = string
  sensitive   = true
  default     = ""
}

# ---- Cloudflare ----
variable "cloudflare_account_id" {
  description = "Cloudflare account ID that owns the R2 bucket."
  type        = string
  default     = ""
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token with R2:Edit + Zone:Edit scopes."
  type        = string
  sensitive   = true
  default     = ""
}

variable "r2_bucket_name" {
  description = "R2 bucket name for artifacts (structures, logs, telemetry)."
  type        = string
  default     = "papercrane-artifacts"
}

variable "r2_bucket_location" {
  description = "R2 bucket location hint (ENAM | WNAM | EU | APAC | OC)."
  type        = string
  default     = "ENAM"
}

# ---- Upstash ----
variable "upstash_email" {
  description = "Upstash account email for API auth."
  type        = string
  default     = ""
}

variable "upstash_api_key" {
  description = "Upstash API key."
  type        = string
  sensitive   = true
  default     = ""
}

variable "upstash_redis_region" {
  description = "Upstash Redis region (us-east-1, eu-west-1, etc)."
  type        = string
  default     = "us-east-1"
}

# ---- Tags ----
variable "tags" {
  description = "Free-form tags applied where supported."
  type        = map(string)
  default = {
    project = "papercrane"
    owner   = "ops"
  }
}
