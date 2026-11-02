/**
 * Demo seed — gives a freshly-wired Supabase project visible content on first
 * login. Creates one user, one org, one project, one target, five jobs across
 * varied states, twenty designs with synthetic but plausible metrics, audit
 * trail, and a usage-ledger row.
 *
 *   pnpm --filter @papercrane/db db:seed:demo            # idempotent upsert
 *   pnpm --filter @papercrane/db db:seed:demo -- --reset # wipe demo org first
 *
 * Reads `SUPABASE_URL` (or `NEXT_PUBLIC_SUPABASE_URL`) and
 * `SUPABASE_SERVICE_ROLE_KEY` from the project-root `.env.local` to drive the
 * Auth admin API. The generated password is written to
 * `<repo>/.agent-logs/20-demo-creds.txt` (chmod 600) and never logged.
 */
import { PrismaClient, Prisma, type Job } from "@prisma/client";
import { createClient } from "@supabase/supabase-js";
import * as fs from "node:fs";
import * as path from "node:path";
import * as crypto from "node:crypto";

// ─── env loader (no extra dep — minimal .env.local parser) ──────────────────
// We avoid pulling `dotenv` into @papercrane/db. The file format we read is
// `KEY=VALUE` per line, optionally quoted, ignoring `#` comments.

const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
const ENV_LOCAL = path.join(REPO_ROOT, ".env.local");
const CREDS_PATH = path.join(REPO_ROOT, ".agent-logs", "20-demo-creds.txt");

function loadEnvLocal(): void {
  if (!fs.existsSync(ENV_LOCAL)) return;
  const raw = fs.readFileSync(ENV_LOCAL, "utf8");
  for (const rawLine of raw.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq < 0) continue;
    const key = line.slice(0, eq).trim();
    let val = line.slice(eq + 1).trim();
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    if (!(key in process.env)) process.env[key] = val;
  }
}

loadEnvLocal();

// ─── constants ──────────────────────────────────────────────────────────────

const DEMO_EMAIL = "demo@papercrane.bio";
const DEMO_ORG_SLUG = "papercrane-demo-lab";
const DEMO_ORG_NAME = "PaperCrane Demo Lab";
const DEMO_STRIPE_CUSTOMER_ID = "cus_demo_papercrane";
const DEMO_STRIPE_SUB_ID = "sub_demo_papercrane";
const PRO_SEED_CAP = 50_000;
const SEEDS_USED_THIS_PERIOD = 142;
const DESIGN_COUNT = 20;

const TOOL_CHAIN = ["rfdiffusion", "proteinmpnn", "boltz2"] as const;

// Deterministic id namespaces — UUIDv5 over the demo email gives us stable
// primary keys across re-runs without storing them anywhere.
const NS = "8c3a2d7e-1b4c-4f9d-9e2a-5d6b7c8a9e10"; // arbitrary fixed UUID
function uuid5(name: string): string {
  // Tiny UUIDv5 implementation (RFC 4122) — avoids adding the `uuid` dep.
  const nsBytes = Buffer.from(NS.replace(/-/g, ""), "hex");
  const hash = crypto.createHash("sha1");
  hash.update(nsBytes);
  hash.update(Buffer.from(name, "utf8"));
  const bytes = hash.digest().subarray(0, 16);
  bytes[6] = (bytes[6] & 0x0f) | 0x50; // version 5
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant RFC 4122
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

const ORG_ID = uuid5("org");
const PROJECT_ID = uuid5("project");
const TARGET_ID = uuid5("target");
const JOB_IDS = {
  succeeded1: uuid5("job:succeeded:1"),
  succeeded2: uuid5("job:succeeded:2"),
  running: uuid5("job:running"),
  queued: uuid5("job:queued"),
  failed: uuid5("job:failed"),
};

// ─── tiny seeded RNG so re-runs produce stable metrics ──────────────────────

function mulberry32(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function randBetween(rng: () => number, lo: number, hi: number): number {
  return lo + rng() * (hi - lo);
}

function randomSequence(rng: () => number, length: number): string {
  const aa = "ACDEFGHIKLMNPQRSTVWY";
  let out = "";
  for (let i = 0; i < length; i++) {
    out += aa[Math.floor(rng() * aa.length)];
  }
  return out;
}

// ─── credential write (chmod 600, never echoed) ─────────────────────────────

function generatePassword(): string {
  // 32 chars from a URL-safe alphabet, ≥ 192 bits of entropy.
  const alphabet =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  const bytes = crypto.randomBytes(32);
  let out = "";
  for (let i = 0; i < 32; i++) out += alphabet[bytes[i] % alphabet.length];
  return out;
}

function writeCreds(password: string, userId: string): void {
  const dir = path.dirname(CREDS_PATH);
  fs.mkdirSync(dir, { recursive: true });
  const body = [
    `# PaperCrane demo credentials — generated ${new Date().toISOString()}`,
    `# DO NOT commit this file. .gitignore'd via .agent-logs/.`,
    `email=${DEMO_EMAIL}`,
    `password=${password}`,
    `user_id=${userId}`,
    `org_id=${ORG_ID}`,
    `org_slug=${DEMO_ORG_SLUG}`,
    "",
  ].join("\n");
  fs.writeFileSync(CREDS_PATH, body, { mode: 0o600 });
  // Tighten existing perms in case the file already existed.
  fs.chmodSync(CREDS_PATH, 0o600);
}

function readExistingPassword(): string | null {
  if (!fs.existsSync(CREDS_PATH)) return null;
  const raw = fs.readFileSync(CREDS_PATH, "utf8");
  const m = raw.match(/^password=(.+)$/m);
  return m ? m[1].trim() : null;
}

// ─── Supabase auth user upsert ──────────────────────────────────────────────

async function ensureDemoAuthUser(): Promise<{ id: string; password: string }> {
  const supabaseUrl =
    process.env.SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!supabaseUrl || !serviceKey) {
    throw new Error(
      "Missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY in .env.local — cannot create demo auth user.",
    );
  }

  const admin = createClient(supabaseUrl, serviceKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });

  // Reuse an existing password from the creds file when re-running so the
  // user logging in with the previously-printed password keeps working.
  const password = readExistingPassword() ?? generatePassword();

  // Look up existing user by listing the first page (small dev project).
  const { data: list, error: listErr } = await admin.auth.admin.listUsers({
    page: 1,
    perPage: 200,
  });
  if (listErr) throw listErr;
  const existing = list.users.find((u) => u.email === DEMO_EMAIL);

  if (existing) {
    // Refresh password + metadata; keep the same id so all FKs stay stable.
    const { error: updErr } = await admin.auth.admin.updateUserById(
      existing.id,
      {
        password,
        email_confirm: true,
        user_metadata: { name: "PaperCrane Demo", demo: true },
      },
    );
    if (updErr) throw updErr;
    writeCreds(password, existing.id);
    return { id: existing.id, password };
  }

  const { data: created, error: createErr } = await admin.auth.admin.createUser(
    {
      email: DEMO_EMAIL,
      password,
      email_confirm: true,
      user_metadata: { name: "PaperCrane Demo", demo: true },
    },
  );
  if (createErr || !created.user) {
    throw createErr ?? new Error("createUser returned no user");
  }
  writeCreds(password, created.user.id);
  return { id: created.user.id, password };
}

// ─── reset path — wipes demo org cleanly ────────────────────────────────────

async function resetDemoOrg(prisma: PrismaClient): Promise<void> {
  // Cascades clean up most child rows; usage_seeds, audit_logs, subscription,
  // featureFlag, projects, targets, jobs, designs are all org-scoped.
  await prisma.$transaction([
    prisma.jobAudit.deleteMany({ where: { job: { orgId: ORG_ID } } }),
    prisma.design.deleteMany({ where: { orgId: ORG_ID } }),
    prisma.usageSeed.deleteMany({ where: { orgId: ORG_ID } }),
    prisma.job.deleteMany({ where: { orgId: ORG_ID } }),
    prisma.target.deleteMany({ where: { orgId: ORG_ID } }),
    prisma.project.deleteMany({ where: { orgId: ORG_ID } }),
    prisma.auditLog.deleteMany({ where: { orgId: ORG_ID } }),
    prisma.subscription.deleteMany({ where: { orgId: ORG_ID } }),
    prisma.featureFlag.deleteMany({ where: { orgId: ORG_ID } }),
    prisma.orgMember.deleteMany({ where: { orgId: ORG_ID } }),
    prisma.organization.deleteMany({ where: { id: ORG_ID } }),
  ]);
}

// ─── job + design fixtures ──────────────────────────────────────────────────

interface JobFixture {
  id: string;
  status:
    | "succeeded"
    | "running"
    | "queued"
    | "failed";
  submittedAt: Date;
  startedAt: Date | null;
  completedAt: Date | null;
  seedsRequested: number;
  seedsConsumed: number;
  gpuSeconds: number;
  costCents: number;
  error: Prisma.InputJsonValue | null;
}

function buildJobFixtures(now: Date): JobFixture[] {
  const day = 24 * 60 * 60 * 1000;
  return [
    {
      id: JOB_IDS.succeeded1,
      status: "succeeded",
      submittedAt: new Date(now.getTime() - 6 * day),
      startedAt: new Date(now.getTime() - 6 * day + 90 * 1000),
      completedAt: new Date(now.getTime() - 6 * day + 47 * 60 * 1000),
      seedsRequested: 12,
      seedsConsumed: 12,
      gpuSeconds: 2_760,
      costCents: 184,
      error: null,
    },
    {
      id: JOB_IDS.succeeded2,
      status: "succeeded",
      submittedAt: new Date(now.getTime() - 2 * day),
      startedAt: new Date(now.getTime() - 2 * day + 60 * 1000),
      completedAt: new Date(now.getTime() - 2 * day + 38 * 60 * 1000),
      seedsRequested: 8,
      seedsConsumed: 8,
      gpuSeconds: 2_220,
      costCents: 148,
      error: null,
    },
    {
      id: JOB_IDS.running,
      status: "running",
      submittedAt: new Date(now.getTime() - 11 * 60 * 1000),
      startedAt: new Date(now.getTime() - 10 * 60 * 1000),
      completedAt: null,
      seedsRequested: 16,
      seedsConsumed: 4,
      gpuSeconds: 600,
      costCents: 40,
      error: null,
    },
    {
      id: JOB_IDS.queued,
      status: "queued",
      submittedAt: new Date(now.getTime() - 90 * 1000),
      startedAt: null,
      completedAt: null,
      seedsRequested: 24,
      seedsConsumed: 0,
      gpuSeconds: 0,
      costCents: 0,
      error: null,
    },
    {
      id: JOB_IDS.failed,
      status: "failed",
      submittedAt: new Date(now.getTime() - 4 * day),
      startedAt: new Date(now.getTime() - 4 * day + 45 * 1000),
      completedAt: new Date(now.getTime() - 4 * day + 9 * 60 * 1000),
      seedsRequested: 10,
      seedsConsumed: 3,
      gpuSeconds: 510,
      costCents: 34,
      error: {
        code: "TOOL_OOM",
        message:
          "boltz2 worker exited with OOM at seed 4 — try reducing batch size or upgrading GPU class.",
        stage: "boltz2",
        seed: 4,
      },
    },
  ];
}

// ─── main ───────────────────────────────────────────────────────────────────

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const reset = args.includes("--reset");

  const prisma = new PrismaClient();
  try {
    // 1) Auth user (Supabase) — creates or refreshes demo@papercrane.bio.
    const { id: userId } = await ensureDemoAuthUser();

    if (reset) {
      await resetDemoOrg(prisma);
    }

    const now = new Date();
    const periodEnd = new Date(now.getTime() + 30 * 24 * 60 * 60 * 1000);
    const jobFixtures = buildJobFixtures(now);
    const rng = mulberry32(0xc4a17e); // stable across runs

    // 2) Single transaction for all relational writes. Auth user must exist
    //    BEFORE this point because `users.id` FKs to `auth.users(id)` via the
    //    on-signup trigger; we still upsert into `public.users` to keep the
    //    Prisma mirror in sync regardless of trigger timing.
    await prisma.$transaction(async (tx) => {
      // Org
      await tx.organization.upsert({
        where: { id: ORG_ID },
        update: {
          slug: DEMO_ORG_SLUG,
          tier: "frontier",
          seedsQuota: PRO_SEED_CAP,
          seedsUsed: SEEDS_USED_THIS_PERIOD,
          retentionDays: 30,
          // Reset GPU budget on re-seed so the demo always starts at a
          // clean $50/$0. Explicit set guards against schema-default drift.
          gpuSpendCapUsd: 50,
          gpuSpendUsd: 0,
        },
        create: {
          id: ORG_ID,
          slug: DEMO_ORG_SLUG,
          tier: "frontier",
          seedsQuota: PRO_SEED_CAP,
          seedsUsed: SEEDS_USED_THIS_PERIOD,
          retentionDays: 30,
          gpuSpendCapUsd: 50,
          gpuSpendUsd: 0,
        },
      });

      // User mirror (Supabase trigger may or may not have inserted yet)
      await tx.user.upsert({
        where: { id: userId },
        update: {
          email: DEMO_EMAIL,
          name: "PaperCrane Demo",
          defaultOrgId: ORG_ID,
        },
        create: {
          id: userId,
          email: DEMO_EMAIL,
          name: "PaperCrane Demo",
          defaultOrgId: ORG_ID,
        },
      });

      // Membership
      await tx.orgMember.upsert({
        where: { orgId_userId: { orgId: ORG_ID, userId } },
        update: { role: "owner" },
        create: { orgId: ORG_ID, userId, role: "owner" },
      });

      // Subscription (Stripe stub)
      await tx.subscription.upsert({
        where: { orgId: ORG_ID },
        update: {
          stripeCustomerId: DEMO_STRIPE_CUSTOMER_ID,
          stripeSubscriptionId: DEMO_STRIPE_SUB_ID,
          status: "active",
          tier: "frontier",
          currentPeriodEnd: periodEnd,
        },
        create: {
          orgId: ORG_ID,
          stripeCustomerId: DEMO_STRIPE_CUSTOMER_ID,
          stripeSubscriptionId: DEMO_STRIPE_SUB_ID,
          status: "active",
          tier: "frontier",
          currentPeriodEnd: periodEnd,
        },
      });

      // Feature flags (frontier demo defaults)
      await tx.featureFlag.upsert({
        where: { orgId: ORG_ID },
        update: {
          retentionDays: 30,
          maxConcurrent: 4,
          vpcEnabled: false,
          closedWeightsAllowed: true,
          byocRequired: false,
          notes: "Demo org — frontier tier defaults",
        },
        create: {
          orgId: ORG_ID,
          retentionDays: 30,
          maxConcurrent: 4,
          vpcEnabled: false,
          closedWeightsAllowed: true,
          byocRequired: false,
          notes: "Demo org — frontier tier defaults",
        },
      });

      // Project
      await tx.project.upsert({
        where: { id: PROJECT_ID },
        update: {
          name: "PD-L1 Binder Discovery",
          orgId: ORG_ID,
          createdBy: userId,
        },
        create: {
          id: PROJECT_ID,
          orgId: ORG_ID,
          name: "PD-L1 Binder Discovery",
          createdBy: userId,
        },
      });

      // Target — PDB 5O45 (PD-L1), chain A, hotspots [54, 56, 115]
      await tx.target.upsert({
        where: { id: TARGET_ID },
        update: {
          orgId: ORG_ID,
          projectId: PROJECT_ID,
          name: "PD-L1 · 5O45",
          pdbId: "5O45",
          artifactKey: "dev/seed/5O45.pdb",
          checksum: "sha256:demo-5g51-fixed-checksum",
          hotspots: { chain: "A", residues: [54, 56, 115] },
        },
        create: {
          id: TARGET_ID,
          orgId: ORG_ID,
          projectId: PROJECT_ID,
          name: "PD-L1 · 5O45",
          pdbId: "5O45",
          artifactKey: "dev/seed/5O45.pdb",
          checksum: "sha256:demo-5g51-fixed-checksum",
          hotspots: { chain: "A", residues: [54, 56, 115] },
        },
      });

      // Jobs
      for (const jf of jobFixtures) {
        const expiresAt = new Date(
          (jf.completedAt ?? jf.submittedAt).getTime() + 30 * 24 * 60 * 60 * 1000,
        );
        const params: Prisma.InputJsonValue = {
          tool_chain: TOOL_CHAIN,
          gpu_seconds: jf.gpuSeconds,
          cost_cents: jf.costCents,
          hotspots: [54, 56, 115],
          chain: "A",
          pdb_id: "5O45",
        };

        await tx.job.upsert({
          where: { id: jf.id },
          update: {
            orgId: ORG_ID,
            projectId: PROJECT_ID,
            targetId: TARGET_ID,
            tool: "rfdiffusion+proteinmpnn+boltz2",
            toolVersion: "rfdiffusion@1.1.0+proteinmpnn@1.0.1+boltz2@0.4.0",
            params,
            seedsRequested: jf.seedsRequested,
            seedsConsumed: jf.seedsConsumed,
            status: jf.status,
            gpuBackend: "modal",
            error: jf.error ?? Prisma.JsonNull,
            submittedAt: jf.submittedAt,
            startedAt: jf.startedAt,
            completedAt: jf.completedAt,
            expiresAt,
          },
          create: {
            id: jf.id,
            orgId: ORG_ID,
            projectId: PROJECT_ID,
            targetId: TARGET_ID,
            tool: "rfdiffusion+proteinmpnn+boltz2",
            toolVersion: "rfdiffusion@1.1.0+proteinmpnn@1.0.1+boltz2@0.4.0",
            params,
            seedsRequested: jf.seedsRequested,
            seedsConsumed: jf.seedsConsumed,
            status: jf.status,
            gpuBackend: "modal",
            error: jf.error ?? Prisma.JsonNull,
            submittedAt: jf.submittedAt,
            startedAt: jf.startedAt,
            completedAt: jf.completedAt,
            expiresAt,
          },
        });

        // JobAudit transitions
        const transitions: Array<{
          from: Job["status"] | null;
          to: Job["status"];
          at: Date;
          actor: string;
          reason?: string;
        }> = [];
        transitions.push({
          from: null,
          to: "queued",
          at: jf.submittedAt,
          actor: userId,
          reason: "submitted",
        });
        if (jf.startedAt) {
          transitions.push({
            from: "queued",
            to: "running",
            at: jf.startedAt,
            actor: "system",
          });
        }
        if (jf.completedAt) {
          transitions.push({
            from: "running",
            to: jf.status,
            at: jf.completedAt,
            actor: "system",
            reason:
              jf.status === "failed"
                ? "tool error: TOOL_OOM"
                : "all seeds delivered",
          });
        }

        // Wipe and re-insert audits for this job to keep idempotent.
        await tx.jobAudit.deleteMany({ where: { jobId: jf.id } });
        for (const t of transitions) {
          await tx.jobAudit.create({
            data: {
              jobId: jf.id,
              fromStatus: t.from ?? undefined,
              toStatus: t.to,
              actor: t.actor,
              reason: t.reason,
              createdAt: t.at,
            },
          });
        }
      }

      // Designs (20 across the two succeeded jobs, 10 each)
      const succeededJobs = [JOB_IDS.succeeded1, JOB_IDS.succeeded2];
      for (let s = 0; s < succeededJobs.length; s++) {
        const jobId = succeededJobs[s];
        await tx.design.deleteMany({ where: { jobId } });
        const perJob = DESIGN_COUNT / succeededJobs.length;
        const designs: Prisma.DesignCreateManyInput[] = [];
        for (let i = 0; i < perJob; i++) {
          const seed = s * 1_000 + i + 1;
          const ipTM = +randBetween(rng, 0.45, 0.85).toFixed(3);
          const pAE = +randBetween(rng, 5, 25).toFixed(2);
          const pDockQ = +randBetween(rng, 0.2, 0.7).toFixed(3);
          const sequence = randomSequence(rng, 80);
          designs.push({
            id: uuid5(`design:${jobId}:${seed}`),
            jobId,
            orgId: ORG_ID,
            seed,
            metrics: {
              ipTM,
              pAE,
              pDockQ,
              sequence,
              length: sequence.length,
              composite: +(0.6 * ipTM + 0.4 * pDockQ).toFixed(3),
            },
            artifactKey: `org/${ORG_ID}/jobs/${jobId}/designs/${seed}.cif`,
            rank: i + 1,
            // Demo fixtures: synthetic metrics, never real model output.
            provenance: "synthetic",
          });
        }
        await tx.design.createMany({ data: designs, skipDuplicates: true });
      }

      // Usage ledger — single rollup row showing 142 seeds consumed.
      await tx.usageSeed.deleteMany({
        where: { orgId: ORG_ID, reason: "demo_period_rollup" },
      });
      await tx.usageSeed.create({
        data: {
          orgId: ORG_ID,
          jobId: null,
          seeds: SEEDS_USED_THIS_PERIOD,
          reason: "demo_period_rollup",
        },
      });

      // AuditLog — privileged-action history visible in dashboard activity.
      await tx.auditLog.deleteMany({
        where: { orgId: ORG_ID, action: "org_created" },
      });
      await tx.auditLog.createMany({
        data: [
          {
            orgId: ORG_ID,
            userId,
            action: "org_created",
            resourceType: "organization",
            resourceId: ORG_ID,
            metadata: { tier: "frontier", source: "seed-demo" },
            createdAt: new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000),
          },
          {
            orgId: ORG_ID,
            userId,
            action: "subscription_upgraded",
            resourceType: "subscription",
            resourceId: ORG_ID,
            metadata: {
              from: "free",
              to: "frontier",
              stripe_customer: DEMO_STRIPE_CUSTOMER_ID,
            },
            createdAt: new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000 + 60_000),
          },
        ],
        skipDuplicates: true,
      });
    });

    // Deliberately quiet — no secrets in stdout. The verifier reads the
    // creds file at .agent-logs/20-demo-creds.txt.
    process.stdout.write(
      `demo seed ok — org=${DEMO_ORG_SLUG} jobs=5 designs=${DESIGN_COUNT}\n`,
    );
  } finally {
    await prisma.$disconnect();
  }
}

main().catch((err) => {
  // eslint-disable-next-line no-console
  console.error("[seed-demo] failed:", err instanceof Error ? err.message : err);
  process.exit(1);
});
