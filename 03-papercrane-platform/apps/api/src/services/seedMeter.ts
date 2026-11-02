import { z } from "zod";
import type { FastifyBaseLogger } from "fastify";
import type { Prisma, PrismaClient } from "@papercrane/db";
import { Sentry } from "@papercrane/observability";

/**
 * Seed-metering service — plan 05-billing-pricing §3.
 *
 * The orchestrator/worker calls POST /v1/seeds/consume every time a seed
 * finishes (success OR graceful failure). This service:
 *
 *   1. Validates the payload.
 *   2. Short-circuits on an Idempotency-Key replay using the `IdempotencyKey`
 *      Prisma model (key namespaced to the org).
 *   3. Atomically debits the org's monthly counter inside a single tenant-
 *      scoped transaction (RLS is applied by the caller via `runInTenantTx`).
 *   4. Emits Sentry `usage.threshold` breadcrumbs at 80% and 95%.
 *   5. Stubs a `seed_overage` Stripe usage record when an org on `overage`
 *      cap crosses the soft cap (actual Stripe call is deferred — see TODO).
 *
 * The route layer (`routes/rest/seeds.ts`) owns HTTP concerns (header parsing,
 * status codes, scope checks). This module is HTTP-agnostic so it can be
 * reused from tRPC or background jobs.
 */

// ─── Input / output contracts ────────────────────────────────────────────────

export const SeedConsumeInputSchema = z
  .object({
    orgId: z.string().uuid(),
    projectId: z.string().uuid(),
    jobId: z.string().uuid(),
    toolChain: z.array(z.string().min(1)).min(1),
    gpuSeconds: z.number().int().nonnegative(),
    costCents: z.number().int().nonnegative(),
    closedWeights: z.boolean(),
  })
  .strict();
export type SeedConsumeInput = z.infer<typeof SeedConsumeInputSchema>;

export interface SeedConsumeResponse {
  seedId: string;
  counted: boolean;
  remainingInPeriod: number;
  /** ISO-8601 UTC timestamp; first day of the next month at 00:00. */
  periodResetsAt: string;
}

export interface QuotaExceededResult {
  quotaExceeded: true;
  counted: false;
  remainingInPeriod: 0;
  seedId: null;
  periodResetsAt: string;
  tier: "free" | "pro" | "frontier";
}

export type ConsumeSeedResult =
  | (SeedConsumeResponse & { quotaExceeded?: false })
  | QuotaExceededResult;

// ─── Tier caps (plan 05 §1 matrix) ───────────────────────────────────────────

export const HARD_CAPS = {
  free: 500,
  pro: 75_000,
  frontier: 1_000_000,
} as const satisfies Record<"free" | "pro" | "frontier", number>;

export const SOFT_CAPS = {
  free: 500,
  pro: 50_000,
  frontier: 1_000_000,
} as const satisfies Record<"free" | "pro" | "frontier", number>;

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * First day of the next month in UTC at 00:00:00. Plan 05 §3 states the
 * monthly billing period resets at the start of the following calendar month.
 */
export function computePeriodResetsAt(now: Date): Date {
  const year = now.getUTCFullYear();
  const month = now.getUTCMonth(); // 0-based
  // Date.UTC handles the December → January rollover automatically.
  return new Date(Date.UTC(year, month + 1, 1, 0, 0, 0, 0));
}

/**
 * Compose the org-scoped idempotency key. The raw header value alone is not
 * safe as a primary key because it could collide across orgs; scoping by
 * orgId keeps us tenant-isolated.
 */
export function buildIdempotencyKey(orgId: string, headerValue: string): string {
  return `seeds:consume:${orgId}:${headerValue}`;
}

function buildScope(orgId: string): string {
  return `seeds:consume:${orgId}`;
}

/**
 * Whether the just-performed debit crossed a percentage threshold of the
 * relevant cap. We look at soft cap for 80% and hard cap for 95% so Free users
 * (soft == hard) still get one late-warning event.
 */
function thresholdsCrossed(
  tier: "free" | "pro" | "frontier",
  prev: number,
  next: number,
): number[] {
  const soft = SOFT_CAPS[tier];
  const hard = HARD_CAPS[tier];
  const crossed: number[] = [];
  const soft80 = Math.ceil(soft * 0.8);
  const hard95 = Math.ceil(hard * 0.95);
  if (prev < soft80 && next >= soft80) crossed.push(0.8);
  if (prev < hard95 && next >= hard95) crossed.push(0.95);
  return crossed;
}

// ─── Dependency injection surfaces ───────────────────────────────────────────

/**
 * Minimal Prisma-tx shape we need. Typed loosely so tests can inject a plain
 * object without reaching for `PrismaClient` (which is a heavy generic type).
 */
export interface SeedMeterTx {
  organization: {
    findUnique: (args: {
      where: { id: string };
      select?: Record<string, boolean>;
    }) => Promise<{
      id: string;
      tier: "free" | "pro" | "frontier";
      seedsUsed: number;
    } | null>;
    update: (args: {
      where: { id: string };
      data: { seedsUsed: { increment: number } };
      select?: Record<string, boolean>;
    }) => Promise<{ seedsUsed: number }>;
  };
  /**
   * Optional surfaces — populated by the production tx runner; tests can omit
   * them and the overage path will skip the Stripe call (the legacy info-log
   * still fires so existing test assertions hold).
   */
  featureFlag?: {
    findUnique: (args: { where: { orgId: string } }) => Promise<{
      orgId: string;
      onCap: "block" | "overage";
    } | null>;
  };
  subscription?: {
    findUnique: (args: { where: { orgId: string } }) => Promise<{
      orgId: string;
      stripeOverageItemId: string | null;
    } | null>;
  };
  auditLog?: {
    create: (args: { data: Record<string, unknown> }) => Promise<unknown>;
  };
  usageSeed: {
    create: (args: {
      data: {
        orgId: string;
        jobId: string;
        seeds: number;
        reason: string;
      };
      select?: Record<string, boolean>;
    }) => Promise<{ id: bigint; createdAt: Date }>;
  };
  idempotencyKey: {
    findUnique: (args: { where: { key: string } }) => Promise<{
      key: string;
      scope: string;
      responseJson: unknown;
      expiresAt: Date;
      createdAt: Date;
    } | null>;
    create: (args: {
      data: {
        key: string;
        scope: string;
        responseJson: unknown;
        expiresAt: Date;
      };
    }) => Promise<unknown>;
  };
}

/**
 * Side-effect surface the overage path needs. Both fields are optional so
 * unit tests can omit them; the production wiring in `routes/rest/seeds.ts`
 * provides real implementations.
 */
export interface OverageRecorder {
  /** Stripe metered-usage call. Returns the usage-record id on success. */
  recordUsage: (args: {
    subscriptionItemId: string;
    quantity: number;
    timestamp: number; // unix seconds
    idempotencyKey: string;
  }) => Promise<{ id: string } | null>;
  /**
   * Redis-backed SETNX guard with 60s TTL. Returns true when the caller is
   * the first writer for `key` in the current minute.
   */
  acquireOnce: (key: string, ttlSec: number) => Promise<boolean>;
}

export interface ConsumeSeedDeps {
  input: unknown;
  idempotencyKey: string;
  runInTenantTx: <T>(fn: (tx: SeedMeterTx) => Promise<T>) => Promise<T>;
  logger: Pick<FastifyBaseLogger, "warn" | "info" | "error">;
  now?: Date;
  /** Sentry.addBreadcrumb-compatible; injected so tests can spy without mocking Sentry. */
  addBreadcrumb?: (crumb: {
    category: string;
    message: string;
    level: "info" | "warning" | "error";
    data: Record<string, unknown>;
  }) => void;
  /** Optional overage recorder — when omitted, only an info log fires. */
  overage?: OverageRecorder;
}

// ─── Core service ────────────────────────────────────────────────────────────

/**
 * Consume one seed. Returns either a success response or a quota-exceeded
 * sentinel that the route layer translates into a 402. Throws on validation
 * errors (ZodError) or missing org.
 */
export async function consumeSeed(
  deps: ConsumeSeedDeps,
): Promise<ConsumeSeedResult> {
  const parsed = SeedConsumeInputSchema.parse(deps.input);
  const now = deps.now ?? new Date();
  const periodResetsAt = computePeriodResetsAt(now).toISOString();
  const key = buildIdempotencyKey(parsed.orgId, deps.idempotencyKey);
  const scope = buildScope(parsed.orgId);
  const ttlExpiresAt = new Date(now.getTime() + 24 * 60 * 60 * 1000);

  return deps.runInTenantTx(async (tx) => {
    // 1) Idempotency short-circuit. If the header was seen in the last 24h,
    //    return the original response body with `counted: false`.
    const cached = await tx.idempotencyKey.findUnique({ where: { key } });
    if (cached && cached.expiresAt > now) {
      const body = cached.responseJson as SeedConsumeResponse;
      return { ...body, counted: false };
    }

    // 2) Load org + current counter.
    const org = await tx.organization.findUnique({
      where: { id: parsed.orgId },
      select: { id: true, tier: true, seedsUsed: true },
    });
    if (!org) {
      // Let the route layer translate this; don't leak which orgs exist.
      throw new Error("org not found");
    }

    // 3) Hard-cap gate. >= because the cap is inclusive upper bound.
    const hardCap = HARD_CAPS[org.tier];
    if (org.seedsUsed >= hardCap) {
      deps.logger.warn(
        { orgId: org.id, tier: org.tier, seedsUsed: org.seedsUsed, hardCap },
        "quota exceeded — seed debit refused",
      );
      return {
        quotaExceeded: true,
        counted: false,
        remainingInPeriod: 0,
        seedId: null,
        periodResetsAt,
        tier: org.tier,
      };
    }

    // 4) Debit path: insert the ledger row, bump the counter, cache the
    //    response — all inside the same transaction.
    const usageSeed = await tx.usageSeed.create({
      data: {
        orgId: parsed.orgId,
        jobId: parsed.jobId,
        seeds: 1,
        // `reason` is a freeform string; we use a stable enum-ish value so
        // downstream reporting can aggregate cleanly.
        reason: parsed.closedWeights ? "consume_closed" : "consume",
      },
    });
    const updated = await tx.organization.update({
      where: { id: parsed.orgId },
      data: { seedsUsed: { increment: 1 } },
    });

    const response: SeedConsumeResponse = {
      seedId: usageSeed.id.toString(),
      counted: true,
      remainingInPeriod: Math.max(0, hardCap - updated.seedsUsed),
      periodResetsAt,
    };

    // 5) Threshold breadcrumbs. Use the caller-provided sink when present
    //    (tests), otherwise fall through to Sentry directly.
    const crossed = thresholdsCrossed(org.tier, org.seedsUsed, updated.seedsUsed);
    for (const threshold of crossed) {
      const crumb = {
        category: "usage.threshold",
        message: `org ${org.id} crossed ${Math.round(threshold * 100)}% seed cap`,
        level: "warning" as const,
        data: {
          orgId: org.id,
          tier: org.tier,
          threshold,
          seedsUsed: updated.seedsUsed,
          hardCap,
        },
      };
      if (deps.addBreadcrumb) {
        deps.addBreadcrumb(crumb);
      } else {
        Sentry.addBreadcrumb(crumb);
      }
    }

    // 6) Overage billing. Plan 05 §3: when org.tier==='pro', the org has
    //    `featureFlag.onCap === 'overage'`, and seedsUsed has crossed the
    //    soft cap, push a Stripe metered usage record on the org's
    //    `seed_overage` subscription item. Idempotent within the minute via
    //    the caller-provided Redis SETNX guard so a retry of the same
    //    Idempotency-Key cannot double-bill.
    //
    //    The info log fires regardless of feature-flag/Stripe wiring so ops
    //    can see overage volume during rollout — tests rely on this signal.
    if (org.tier === "pro" && updated.seedsUsed > SOFT_CAPS.pro) {
      const overageQuantity = updated.seedsUsed - SOFT_CAPS.pro;
      deps.logger.info(
        {
          orgId: org.id,
          seedsUsed: updated.seedsUsed,
          overageQuantity,
        },
        "pro org in overage range",
      );

      if (deps.overage && tx.featureFlag && tx.subscription) {
        try {
          const flag = await tx.featureFlag.findUnique({
            where: { orgId: parsed.orgId },
          });
          if (flag?.onCap === "overage") {
            const sub = await tx.subscription.findUnique({
              where: { orgId: parsed.orgId },
            });
            const itemId = sub?.stripeOverageItemId;
            if (!itemId) {
              deps.logger.warn(
                { orgId: org.id },
                "overage triggered but no stripe_overage_item_id on subscription",
              );
            } else {
              // Minute-bucketed SETNX guard — same Idempotency-Key inside
              // the same minute is a no-op (re-tries that crossed retry
              // boundaries get the same `counted: false` cached body via
              // the idempotency table, but a same-key/same-minute replay
              // that DID make it past the cache won't double-record).
              const minuteBucket = Math.floor(now.getTime() / 60_000);
              const guardKey = `seed_overage:${parsed.orgId}:${deps.idempotencyKey}:${minuteBucket}`;
              const isFirst = await deps.overage.acquireOnce(guardKey, 60);
              if (isFirst) {
                const result = await deps.overage.recordUsage({
                  subscriptionItemId: itemId,
                  quantity: overageQuantity,
                  timestamp: Math.floor(now.getTime() / 1000),
                  idempotencyKey: `seed_overage:${parsed.orgId}:${deps.idempotencyKey}`,
                });
                if (tx.auditLog) {
                  await tx.auditLog.create({
                    data: {
                      orgId: org.id,
                      // Prisma enum value (DB-mapped to "billing.overage_recorded").
                      action: "billing_overage_recorded",
                      resourceType: "subscription_item",
                      resourceId: itemId,
                      metadata: {
                        usageRecordId: result?.id ?? null,
                        quantity: overageQuantity,
                        seedsUsed: updated.seedsUsed,
                        tier: org.tier,
                      },
                    },
                  });
                }
              }
            }
          }
        } catch (err) {
          // Don't fail the seed debit on a billing-side error — the seed
          // already counted, surface the failure for ops to reconcile.
          deps.logger.error(
            { err, orgId: org.id },
            "overage usage record failed",
          );
        }
      }
    }

    // 7) Persist the idempotency record so a retry returns the same body.
    await tx.idempotencyKey.create({
      data: {
        key,
        scope,
        responseJson: response as unknown as Prisma.InputJsonValue,
        expiresAt: ttlExpiresAt,
      },
    });

    return response;
  });
}

// ─── Adapter for the route layer ─────────────────────────────────────────────

/**
 * Factory that binds `consumeSeed` to a real Prisma client via
 * `withRlsUser`-style transaction semantics. The route handler keeps this
 * lightweight adapter around so it doesn't need to know about the DI shape.
 */
export interface BuildRunnerDeps {
  prisma: PrismaClient;
  runWithTenant: <T>(fn: (tx: Prisma.TransactionClient) => Promise<T>) => Promise<T>;
}

export function buildTenantTxRunner(deps: BuildRunnerDeps) {
  return async <T>(fn: (tx: SeedMeterTx) => Promise<T>): Promise<T> => {
    return deps.runWithTenant((tx) => fn(tx as unknown as SeedMeterTx));
  };
}
