# Paper Crane Compute Infrastructure Plan

**Scope:** GPU orchestration layer beneath job execution. Multi-cloud, tier-aware, margin-positive.
**Authors:** Infra track, Paper Crane founding team (2-person).
**Target:** YC S26 demo-ready by Day 14.

---

## 1. Architecture Overview

Paper Crane runs a thin **compute router** (`pc-router`) in front of every GPU provider. The router exposes a single internal API:

```
POST /jobs { tool, params, tier, org_id, priority, budget_cap }
  → { job_id, provider, eta_seconds, estimated_cost }
```

Behind that API, adapters translate to Modal functions, Vast.ai instance rentals, RunPod pods, Lambda on-demand, or a customer-provided endpoint. The router owns: provider selection, queue, budget enforcement, retry, and cost attribution. The adapters own: container spawn, log relay, artifact upload.

**Why this shape:** 2-person team cannot run Kubernetes. Modal + Vast.ai + Runpod already solve scheduling; we just pick which one and track spend.

---

## 2. Provider Evaluation Matrix (2026 estimates)

| Provider | A100-80GB $/hr | H100 $/hr | Cold start | Reliability | API maturity | Container support | Role |
|---|---|---|---|---|---|---|---|
| **Modal** | $3.40 | $5.12 | 4–12s (warm pool) | 99.9% | Excellent (Python-native) | OCI + custom images | **Primary managed** |
| **Vast.ai** | $0.80–1.50 (spot) | $1.90–2.80 | 30–90s | 97–98% (variable host) | Decent REST | Docker only | **Cost-optimized batch** |
| **RunPod** | $1.89 (community), $2.89 (secure) | $2.99–4.18 | 15–45s | ~99% | Good GraphQL+REST | Docker + serverless | **Fallback + BYOC** |
| **Lambda Labs** | $1.79 reserved | $2.99 | 2–5 min (provision) | 99% | Thin REST | Manual SSH | Long reserved only |
| **AWS/GCP direct** | $5.12 / $3.67 | $9.80 / $11.06 | 3–8 min | 99.99% | Enterprise | Full | **Frontier VPC only** |

**Recommendation:** Modal primary, Vast.ai cost-optimizer, RunPod reliability fallback. Lambda deferred until we have >$50K/mo reserved workload. Direct hyperscaler only for Frontier VPC deployments.

---

## 3. Multi-Provider Compute Router

**Selection strategy** per job, in order:

1. **Hard filter:** does provider have the requested GPU + VRAM + driver?
2. **Tier pin:** Frontier org → dedicated cluster only. Pro default → Modal. Free (BYOC) → user's provider only.
3. **Score:** `score = w_cost * $/hr_normalized + w_latency * cold_start + w_reliability * (1 - uptime)`. Weights shift by tool: BindCraft-slow (12h) weights cost high, prefers Vast.ai spot; ProteinMPNN (5 min) weights latency high, stays on Modal warm pool.
4. **Fallback:** if primary pool saturated OR bid not filled in 60s, re-dispatch to #2.

Router is a small FastAPI service + Postgres (jobs, attempts, cost ledger) + Redis (queues). Deployed on Fly.io — cheap, multi-region, no GPU.

---

## 4. BYOC Architecture (Free Tier)

Free users bring their own Modal / RunPod / Vast.ai key. We never see their GPU dollars.

**Flow:**
1. User pastes API key into settings. Client-side encrypted with user's passphrase (PBKDF2) and sent to us.
2. Server-side: key is re-encrypted with **AWS KMS envelope encryption** under a per-org data key, stored in Postgres. Plaintext never at rest.
3. At job time, router decrypts in-memory, signs a provider request using the key, discards key from memory.
4. Cost attribution: we read provider's billing API (Modal has `modal.billing.query`, RunPod has `/v2/user/invoices`) hourly and display their spend in our dashboard. We charge **$0**.
5. Rate limit: 5 concurrent jobs per free org to cap our orchestration cost (~$0 GPU, ~$0.001 router CPU).

**Security controls:** KMS CMK with key rotation, audit log on every decrypt, CSP-restricted dashboard, key scopes suggested in docs ("create a Modal token limited to `workspace: paper-crane-free`").

---

## 5. Managed GPU Pool (Pro Tier)

**Pool composition (steady state):**

- **Warm pool:** 4× A100-80GB on Modal, always-on. Holds RFdiffusion, ProteinMPNN, Boltz-2 containers with weights pre-loaded. Cost: ~$325/day = $9.8K/mo.
- **Burst on-demand:** Modal auto-scales to 40 concurrent A100s, billed per-second.
- **Spot batch:** Vast.ai bids for long jobs (BindCraft slow, AF2 relaxation). Triggered when queue has >20 jobs with latency budget >30 min.
- **On-demand mix target:** 30% warm / 50% burst on-demand / 20% Vast.ai spot.

**Auto-scale triggers:**
- Queue depth > 2× warm pool size → spin up 4 more A100s (Modal).
- Queue depth > 50 with latency-tolerant jobs → dispatch Vast.ai bid.
- Warm pool idle > 10 min → scale down to 2.

**Cost ceiling per org:** Pro plan = 50,000 seeds/mo. At $0.80 blended COGS per seed we spend $40K to collect $299 × N customers. **Break-even at ~134 Pro customers** contributing $40K revenue; per-customer margin positive only if they use <180 seeds/mo average. Enforcement: soft cap at 50K seeds, hard cap at 75K, overage meters to $0.01/seed.

---

## 6. Dedicated Cluster (Frontier Tier — $50K+/yr)

Three deployment shapes, customer picks:

1. **Dedicated Modal workspace** — we create a Modal sub-account, our code deploys there, customer pays Modal directly + our platform fee. Fastest to set up (2 days). Good for $50K–150K/yr.
2. **Vast.ai reserved** — 8× A100-80GB committed for 6 months at ~$0.65/hr/GPU = $22.5K/6mo. We operate, customer pays. Good for compute-heavy batch.
3. **BYOC-enterprise** — customer provides AWS/GCP account with GPU quota. We deploy via Terraform: EKS/GKE + Karpenter + our router in their VPC. HIPAA/SOC2 path. Deal size $200K+.

**Cost model:** infra pass-through + 25% platform margin + $75K/yr managed support retainer. Priority queue: Frontier jobs preempt nothing but skip Pro queue.

---

## 7. Job Queue + Priority

Single Redis Streams queue per GPU class, with **weighted fair queueing**:

- Frontier: weight 10, dedicated stream, never blocked by other tiers.
- Pro: weight 3, shared burst pool.
- Free/BYOC: weight 1, own-compute only (no contention with us).

Per-org token bucket prevents one Pro customer from monopolizing the burst pool. Backpressure: when burst pool + Vast.ai fallback both saturate, new Pro jobs get `eta_seconds` returned and client shows "Queued — 14 min". Hard ceiling: 500 in-flight Pro jobs globally.

**Retry:** spot preemption → automatic re-dispatch to on-demand after 1 retry. Max 3 retries; after that, refund the seed credit.

---

## 8. Cost Tracking + Budget Enforcement

Counters (Postgres, updated every job transition):

- `org_spend_month_usd`
- `org_seeds_month`
- `org_gpu_seconds_by_type`
- `tool_spend_by_day` (for our margin analysis)

Stripe integration (handled by plan 05) consumes these counters:
- Subscription: flat $299 Pro.
- Metered overage: `seed_overage` SKU at $0.01, emitted when `org_seeds_month > 50000`.
- Frontier: invoiced monthly from `org_spend_month_usd + margin`.

**Auto-pause:** soft alert at 80% of org budget, hard pause at 100%. Running jobs finish; new submissions return `402 Payment Required`. Recovery on budget bump or cycle reset.

---

## 9. Cold-Start Optimization

**Target: first seed running within 60s of submit.**

Levers:
- **Shared base image:** single `paper-crane/base:cuda12.4-torch2.6` layered with tool-specific deltas. Modal keeps 5 warm.
- **Weight caching:** RFdiffusion (~1.5 GB), ProteinMPNN (~80 MB), Boltz-2 (~2.4 GB), AF2/Chai weights mounted via Modal Volume (persistent, cross-region replicated). Saves 4–8 min download per cold container.
- **Warm pool:** always 4× A100 idle holding the top-3 tools in RAM.
- **Early dispatch:** router enqueues to GPU before validation finishes (validation runs on CPU while GPU spins).
- **Tool-specific init:** ProteinMPNN loads model at import, not per-job.

Expected cold start distribution: 65% of jobs ≤ 10s (warm hit), 30% ≤ 60s (burst), 5% up to 180s (Vast.ai bid).

---

## 10. Data Egress Strategy

Artifacts (PDBs, metrics JSON, trajectories) written to **per-region object storage**:

- US jobs → Cloudflare R2 `us-east` (R2 has $0 egress — keeps our costs flat).
- EU jobs → R2 `eu-west`.
- Frontier BYOC → customer's S3/GCS in their VPC.

Public benchmark results (the $257/540-run dataset on landing page) served via Cloudflare CDN from R2. No AWS egress anywhere in the critical path. Signed URLs for private Pro artifacts, 7-day expiry, rotating keys.

---

## 11. Monitoring

Grafana + Prometheus (self-hosted on Fly). Dashboards:

- **GPU utilization** per provider, per GPU type, 1-min granularity.
- **Queue depth** per tier, p50/p95 wait time.
- **Provider reliability** — rolling 24h success rate per provider.
- **Cost per tool per day** — spots margin drift immediately.
- **Cold-start histogram.**

PagerDuty on: queue wait p95 > 5 min, any provider success rate < 95% over 15 min, daily burn > 150% of 7-day average.

---

## 12. Build Sequence (5 Milestones)

| M# | Days | Deliverable | Unlocks |
|---|---|---|---|
| M1 | 0–3 | Modal-only managed path, 3 tools (RFdiff, MPNN, Boltz-2), warm pool, Postgres cost ledger | Internal demo, benchmark dataset |
| M2 | 4–6 | BYOC free tier with Modal + RunPod adapters, KMS key storage | Launch free plan, YC demo |
| M3 | 7–9 | Vast.ai spot fallback + router scoring + retry | Margin compression on long jobs |
| M4 | 10–12 | Pro budget enforcement + Stripe metering hooks + monitoring dashboards | Paid GA |
| M5 | 13–21 | Frontier dedicated Modal workspace + Terraform for BYOC-enterprise | First pharma pilot |

---

## 13. Unit Economics (Pro tier, managed pool)

| Tool | Avg GPU-min | Provider | GPU $/hr | Cost/seed | Pro price/seed | Margin |
|---|---|---|---|---|---|---|
| ProteinMPNN | 5 | Modal A100 | $3.40 | $0.28 | $0.50 | 44% |
| RFdiffusion (100 designs) | 18 | Modal A100 | $3.40 | $1.02 | $1.50 | 32% |
| Boltz-2 validation | 8 | Modal A100 | $3.40 | $0.45 | $1.00 | 55% |
| AF2-Multimer | 22 | Vast.ai spot | $1.20 | $0.44 | $1.25 | 65% |
| BindCraft slow | 180 | Vast.ai spot | $1.20 | $3.60 | $5.00 | 28% |
| **Blended (weighted)** | — | — | — | **$0.78** | **$1.45** | **46%** |

Blended margin 46% hits our 60% Pro target only if we shift >40% of long jobs to Vast.ai spot. M3 is critical for this.

---

## 14. Sequence Diagram — Submit → Result

```
User          Web API       Router        Queue      Provider Adapter     GPU         R2 Storage
 |              |              |             |              |              |              |
 |--submit----->|              |             |              |              |              |
 |              |--validate--->|             |              |              |              |
 |              |              |--budget chk-|              |              |              |
 |              |              |--score+pick provider(Modal)|              |              |
 |              |              |--enqueue--->|              |              |              |
 |              |<-job_id------|             |              |              |              |
 |<-202 eta=8s--|              |             |              |              |              |
 |              |              |             |--dequeue---->|              |              |
 |              |              |             |              |--spawn------>|              |
 |              |              |             |              |              |--load wt (cached)
 |              |              |             |              |              |--run tool
 |              |              |             |              |              |--write PDB-->|
 |              |              |             |              |<-done+cost---|              |
 |              |              |<-update ledger+status------|              |              |
 |              |              |--signed URL------------------------------->              |
 |--poll/WS---->|              |             |              |              |              |
 |<-result URL--|              |             |              |              |              |
```

Retry loop: on spot-preempt event from adapter → router re-enqueues with `attempt=2, provider=Modal-ondemand`. On third failure → refund seed credit, page on-call.

---

## 15. Risks + Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Modal outage | Pro tier down | Router auto-drains to RunPod; status page; SLA credit |
| Vast.ai host flakes | Spot jobs fail | Max 1 spot retry, then on-demand; reliability score per host, blacklist <95% |
| H100 price spike (demand shock) | Margin collapse | Weekly provider price poll; route H100-optional tools to A100 automatically |
| User runs away a budget loop | Runaway spend | Per-org daily hard cap; job-level `max_gpu_minutes`; anomaly detection |
| Subscription < COGS for power user | Lose money on Pro | Seed overage metered from seed 50,001 at $0.01; fair use ToS |
| KMS key leak (BYOC) | Breach of free users' clouds | Envelope encryption, key rotation 90d, short-lived in-memory decrypt, SOC2 on roadmap |
| Weights cache corruption | All jobs fail | Content-addressed weights with SHA256 verification on mount |
| Vast.ai disappears from market | Lose 40% margin | RunPod community tier is structurally similar; M3 includes both adapters |

---

**Bottom line:** Modal gets us to demo in 3 days. Vast.ai gets us to margin by day 10. BYOC gets us YC-friendly free-tier economics from day 6. Frontier VPC is Terraform templates we write once and sell against for 18 months.
