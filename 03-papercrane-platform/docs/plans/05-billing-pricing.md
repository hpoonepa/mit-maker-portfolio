# Paper Crane — Billing + Pricing Enforcement Plan

## 1. Feature Matrix by Tier

| Capability | Free | Pro ($299/mo) | Frontier ($50K+/yr) |
|---|---|---|---|
| Seeds/month included | 500 | 50,000 | Unlimited (soft cap 1M/mo) |
| Open-source tools (RFdiffusion, ProteinMPNN, Boltz2, Chai-1) | Yes | Yes | Yes |
| Closed-weight models (AF3-Pro, internal diffusion) | No | No | Yes |
| Compute | BYOC only | Managed GPU (A100/H100 pool) | Dedicated cluster |
| VPC deploy | No | No | Yes (Terraform, AWS/GCP/Azure) |
| Job retention | 7 days | 90 days | 365 days or custom |
| Max concurrent jobs | 2 | 20 | 200 |
| Seats | 1 | Up to 10/org (cap raise $50/seat) | Unlimited |
| Top-up packs | No | Yes | N/A |
| SLA | None | 99.5% best-effort | 99.9% contractual |
| Support | Community Discord | Email, 24h | Shared Slack, 4h |
| MSA / DPA / BAA | No | Standard ToS | Custom signed |

## 2. Stripe Data Model

```
Organization (PaperCrane DB)
   |
   └── stripe_customer_id ──> Stripe.Customer
                                  |
                                  ├── Stripe.Subscription (Pro monthly/annual)
                                  │      ├── Price: price_pro_monthly_299
                                  │      ├── Price: price_pro_annual_2990 (17% off)
                                  │      └── Item: metered_seats (qty = active users)
                                  │
                                  ├── Stripe.Subscription (Top-up, one-shot via Invoice)
                                  │      └── Price: price_pack_10k_seeds_99
                                  │
                                  └── Stripe.Invoice (Frontier, manual, net-30)
                                         └── Line items: platform fee, GPU hours, setup
```

Four Price objects only at launch: `pro_monthly`, `pro_annual`, `seat_addon_50`, `seed_pack_10k_99`. Frontier does not use Stripe Subscription — it uses raw Invoice objects. Webhooks we handle: `customer.subscription.created|updated|deleted`, `invoice.payment_failed`, `invoice.paid`, `customer.subscription.trial_will_end`. Dunning: Stripe's Smart Retries + 3 emails (day 1, 3, 7); day 10 downgrade to Free.

## 3. Seed Metering

A seed is counted when the orchestrator emits `seed.completed` (success OR graceful failure). Crashes during first 30 seconds do not count. Accounting is real-time for enforcement but rolls up daily for billing.

```python
POST /v1/seeds/consume
Headers: Authorization: Bearer <org-token>
         Idempotency-Key: <uuid-v7>   # required
Body: {
  "org_id": "org_7f3a",
  "project_id": "proj_rbx1",
  "tool_chain": ["rfdiffusion", "proteinmpnn", "boltz2"],
  "gpu_seconds": 142,
  "cost_cents": 8,
  "closed_weights": false
}
Response: {
  "seed_id": "seed_01HXZ...",
  "counted": true,
  "remaining_in_period": 48213,
  "period_resets_at": "2026-05-01T00:00:00Z"
}
```

Idempotency-Key deduplicates retries within 24h (stored in Redis). Primary counter lives in Postgres `seed_usage` table (org_id, period_start, count, gpu_seconds) updated via `UPDATE ... RETURNING` for atomicity. Redis cache holds the current-period count for sub-10ms gate checks.

**Cap behavior** is org-configurable in settings: `on_cap = "block" | "overage"`. Block returns HTTP 402. Overage bills `$0.012/seed` for Pro (post-cap) via metered Stripe subscription item, invoiced end-of-month. Rate limits enforced per-tier at the gateway (Free: 5 req/min, Pro: 200 req/min, Frontier: unthrottled).

## 4. Tier Enforcement Gateway

Single middleware `enforce_tier(request)` runs on every `/v1/*` call:

1. Resolve org → tier from `feature_flags` table (cached 60s in Redis).
2. Check tool against `tool_allowlist[tier]`.
3. Check `seed_usage[period]` vs `seed_cap[tier]`.
4. Check `concurrent_jobs[org]` vs `max_concurrent[tier]`.
5. Log decision to audit trail.

`feature_flags` table is the single source of truth (one row per org, not per tier) so Frontier customers get custom overrides without code changes: `retention_days`, `max_concurrent`, `vpc_enabled`, `closed_weights_allowed`, `byoc_required`.

## 5. Overage + Top-Up

Pro dashboard shows a meter that turns yellow at 80%, red at 95%. Red state shows a modal: "Buy 10,000 seeds for $99" (one-click Stripe Checkout, uses saved card). No subscription change. Top-up seeds expire in 90 days, consumed AFTER monthly allotment. Packs: 10k/$99, 50k/$399, 200k/$1,299.

## 6. Frontier Contracts

Manual handshake (Founder Sales until we hire AE). Template MSA (Common Paper + Orrick SaaS template as starting point) + DPA + SOC2-lite attestation. Invoice generation via Stripe Invoice API with custom line items, net-30 default, net-60 negotiable >$150K. PO numbers stored on Invoice metadata. No auto-collect — CFO wires ACH. Annual prepay standard, quarterly available. Contracts tracked in a Notion CRM until deal count >10, then migrate to HubSpot.

## 7. Free Tier Abuse

- GitHub OAuth preferred, email+password requires verification link.
- One Free org per GitHub account; email domain throttle (max 5 Free orgs/domain except known providers).
- IP signup throttle: 3 orgs/IP/day.
- Hard budget cap: 500 seeds/month, cannot be raised, cannot be "overage'd".
- Abuse heuristics: identical job hashes across orgs, referral chains, residential proxy signatures trigger manual review.
- First 30 days require GitHub account >90 days old.

## 8. VPC Deploy Cost Model (Frontier)

Two-line model: **Setup fee $25K** (one-time, covers Terraform customization, VPC peering, 2 weeks of engineering) + **Platform fee $50K–$250K/yr** depending on seat count and SLA. Compute is **pass-through with 15% markup** when we operate the cluster; **zero markup** when customer supplies their own GPUs (most common — pharma already has A100 fleets). Markup covers monitoring, autoscaling, and on-call rotation. Terraform modules published as private artifact; customer runs `terraform apply` in their AWS/GCP.

## 9. Multi-Seat for Pro

**Per-org pricing with seat cap** — $299/mo includes 10 active seats, additional seats $50/mo each (metered Stripe subscription item). Per-org chosen because it aligns with how labs work (one PI pays, grad students come and go). "Active seat" = logged in or submitted a job in the billing period. Org admin invites via email, SSO available from 5 seats up. Shared projects with RBAC (owner/editor/viewer).

## 10. Usage Dashboard

Single page, three widgets: (1) seeds consumed this period with projection line hitting end-of-month, (2) GPU-hours per tool (stacked bar), (3) top 10 users by seed spend. Forecasting is linear extrapolation from last 7 days with seasonality override (weekend dip). Projection warning when forecast >110% of cap.

## 11. Revenue Recognition + Accounting

ARR = sum of active Pro MRR × 12 + Frontier contract value / contract months × 12. Stripe Sigma for SQL on revenue data, piped nightly to Metabase dashboard. ASC 606: monthly subscription revenue recognized ratably; annual prepay booked as deferred revenue, amortized monthly; one-time setup fees (Frontier) recognized over contract term; seed packs recognized on consumption (not on purchase) to match delivery. Bookkeeper (Pilot or Kick, ~$400/mo) handles filings.

## 12. Pricing Iteration Roadmap (first 6 months)

- **Month 1–2**: ship baseline, no A/B. Goal = first 20 paying Pro orgs.
- **Month 3**: A/B Pro price ($299 vs $399 vs $249) on new signups only, n=100/arm.
- **Month 4**: A/B Free seed cap (500 vs 1,000 vs 2,000) — measure Free→Pro conversion, not signups.
- **Month 5**: Test annual discount depth (15% vs 20% vs 25%).
- **Month 6**: Introduce team/Startup tier if data shows gap between Pro and Frontier.

Watched metrics: signup → activated (ran ≥1 seed) → paid conversion, 30/60/90-day churn, net revenue retention, expansion from top-ups, Frontier pipeline $.

## 13. Unit Economics (per seed)

| Tool chain | GPU-s | Cost | Price charged (Pro) | Margin |
|---|---|---|---|---|
| RFdiffusion + MPNN + Boltz2 (standard) | 140s A100 | $0.055 | $0.006 (bundled) | 89% blended at 50K seeds |
| Protenix2025 + Boltz2 | 220s A100 | $0.086 | $0.006 | 85% |
| AF3-Pro + internal diffusion (Frontier only) | 400s H100 | $0.31 | $0.05 pass-through +15% | 15% markup |
| Chai-1 only (validation) | 60s A100 | $0.023 | $0.006 | 94% |

At $299/mo ÷ 50,000 seeds = $0.00598/seed effective. Compute cost at current Vast.ai A100 rates (~$1.40/hr) averages $0.058/seed across mix → gross margin ~90% at full utilization. Margin collapses to ~40% at 10% utilization, which is why the included cap is generous: we want heavy users, not idle subs.

## 14. Build Sequence

- **M1 (week 1)**: Stripe Checkout for Pro monthly, webhook handler, `organizations` + `subscriptions` tables, basic tier flag.
- **M2 (week 2)**: Seed metering API with idempotency, enforcement middleware, Redis counter.
- **M3 (week 3)**: Stripe Customer Portal embed, self-serve cancel/upgrade, dunning emails.
- **M4 (week 4)**: Top-up packs, usage dashboard, projection widget.
- **M5 (week 6–8)**: Frontier Invoice flow, MSA template, Terraform VPC module, feature flag overrides per-org.

## 15. Risks + Mitigations

- **Seed cost drift** (GPU prices rise): quarterly cost review; contracts allow 10% price adjustment with 60-day notice; multi-cloud (Vast.ai + Lambda + Modal) keeps us within 20% of spot floor.
- **Chargebacks**: require email verification + 3DS for cards >$500; dispute automation via Stripe Radar; Frontier wired ACH only.
- **Tier boundary confusion** (users expect closed models on Pro): in-dashboard tool picker greys out Frontier-only tools with "Contact sales" CTA; pricing page lists exact tool names, not vague categories.
- **Free-tier cost blowout**: hard 500-seed cap is non-negotiable in code (not feature flag); Free users land on spot-only GPU queue (up to 6x cheaper); abuse sweeps weekly.
- **Frontier deal slippage** (6–9 month sales cycles): don't count Frontier in MRR forecast until signed; Pro must independently reach $1M ARR path (~280 orgs) to de-risk.
