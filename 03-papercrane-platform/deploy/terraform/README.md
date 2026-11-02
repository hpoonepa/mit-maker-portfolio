# Paper Crane — Terraform (optional)

These configs provision the cloud side-stack that Paper Crane depends on:

- **Supabase** — Postgres + Auth + Storage (limited TF coverage, mostly CLI)
- **Cloudflare R2** — S3-compatible artifact store
- **Upstash** — managed Redis for BullMQ + rate limiting

They are **optional**. For the first deploy, clicking through the dashboards is
faster. Once stable, import existing resources into state and use TF for drift
control and secret rotation.

---

## Prerequisites

```bash
brew install terraform supabase/tap/supabase flyctl
npm i -g vercel wrangler
```

Accounts needed (free tiers are fine to start):
- Supabase (supabase.com)
- Cloudflare (cloudflare.com) — with R2 enabled
- Upstash (upstash.com)

Export these before running any `terraform` command:

```bash
export SUPABASE_ACCESS_TOKEN="sbp_..."           # personal access token
export TF_VAR_cloudflare_api_token="..."          # Cloudflare API token
export TF_VAR_cloudflare_account_id="..."
export TF_VAR_upstash_email="you@domain.com"
export TF_VAR_upstash_api_key="..."
export TF_VAR_supabase_project_ref="..."         # from CLI bootstrap below
export TF_VAR_supabase_db_password="..."         # from CLI bootstrap below
```

Or drop them in `terraform.tfvars` (gitignored).

---

## Bootstrap

### 1. Create the Supabase project (CLI — once)
The Supabase Terraform provider does not yet cover project creation, so we use
the CLI:

```bash
supabase login
supabase projects create papercrane-prod \
  --org-id <ORG_ID> \
  --db-password <STRONG_PASSWORD> \
  --region us-east-1
```

Copy the returned `ref` into `TF_VAR_supabase_project_ref`, and the password
into `TF_VAR_supabase_db_password`.

### 2. Push the schema
```bash
supabase link --project-ref $TF_VAR_supabase_project_ref
supabase db push --file packages/db/migrations
```

### 3. Apply Terraform (R2 + Upstash)
```bash
cd deploy/terraform
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

### 4. Read outputs
```bash
terraform output -json secret_bundle > /tmp/pc-secrets.json
# feed into: scripts/sync-secrets-to-fly.sh
# feed into: scripts/sync-secrets-to-vercel.sh
```

> Never commit `terraform.tfstate` — it contains secrets. Remote backend
> (Terraform Cloud or s3+dynamodb) is recommended for team setups.

---

## Layout

| File             | Owns                                                |
|------------------|-----------------------------------------------------|
| `variables.tf`   | Input vars + validation                             |
| `supabase.tf`    | Placeholders + computed DSNs (project is CLI-made)  |
| `r2.tf`          | R2 bucket + CORS + lifecycle + scoped API token     |
| `upstash.tf`     | Redis queue + optional cache DB                     |
| `outputs.tf`     | Sensitive bundle consumed by CI                     |

---

## Destroy / tear down

```bash
terraform destroy -target=upstash_redis_database.queue
terraform destroy -target=cloudflare_r2_bucket.artifacts
# Supabase: delete via dashboard or `supabase projects delete <ref>`
```

---

## Why not 100% TF?

1. Supabase API is CLI-first; TF provider covers ~20% of surface area.
2. Stripe doesn't have a useful TF provider — one-time setup in dashboard.
3. Sentry + PostHog provisioning is a 30-second dashboard task, not worth
   dragging into TF for a seed-stage project.
4. Domain/DNS we keep manual until we move registrars.

Full deploy flow lives in `deploy/README.md`.
