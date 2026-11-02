/**
 * Jobs router — submit / get / list / cancel.
 *
 * `submit` enforces the tier→tool allowlist and a seed quota check, inserts
 * the job row inside an RLS transaction, enqueues onto the tier's BullMQ
 * queue (`JOB_QUEUE_NAMES[tier]`), and returns the row plus an estimated
 * ETA.
 *
 * `cancel` sets status='cancelling' transactionally then publishes on
 * Redis pubsub. The worker is responsible for the actual teardown; the
 * router only records intent.
 */
import { z } from "zod";
import {
  JobSubmissionSchema,
  JobSummarySchema,
  getPapercraneWorkflow,
  workflowToolId,
} from "@papercrane/types";
import { JOB_QUEUE_NAMES } from "@papercrane/jobs";
import {
  estimateJobCost,
  DEFAULT_FALLBACK_GPU,
  DEFAULT_SECONDS_PER_DESIGN,
} from "@papercrane/billing";
import { Prisma } from "@papercrane/db";
import { router, publicProcedure, TRPCError } from "../trpc.js";
import { requireAuth } from "../middleware/auth.js";
import { isToolAllowedForTier } from "../config/tierTools.js";
import { isToolRunnable } from "../config/toolReadiness.js";
import { validateToolParameters } from "../config/toolInputValidation.js";

const protectedProcedure = publicProcedure.use(requireAuth);

/**
 * Beta guardrail: max seeds a single job may request. Default 25, overridable
 * via `PAPERCRANE_MAX_SEEDS_PER_JOB`.
 *
 * WHY: seed fan-out is bounded, so very large requests can still consume
 * excessive provider capacity and signed-URL lifetime. Keep the cap until
 * production load data supports raising it.
 */
const MAX_SEEDS_PER_JOB = 25;

/** Resolve the per-job seed cap at call time so env overrides take effect. */
function maxSeedsPerJob(): number {
  const raw = process.env.PAPERCRANE_MAX_SEEDS_PER_JOB;
  const parsed = raw ? Number.parseInt(raw, 10) : Number.NaN;
  return Number.isInteger(parsed) && parsed >= 1 ? parsed : MAX_SEEDS_PER_JOB;
}

const SubmitOutput = JobSummarySchema.extend({
  etaSeconds: z.number().int().nonnegative(),
});

/**
 * Detail wire shape for `jobs.get` — the compact {@link JobSummarySchema}
 * plus the reproducibility provenance the UI surfaces: the resolved tool
 * version, adapter version, container image digest, and the verbatim run
 * params that were submitted. All provenance fields are nullable so jobs
 * created before the provenance migration still validate.
 */
const JobDetailOutput = JobSummarySchema.extend({
  toolVersion: z.string().nullish(),
  adapterVersion: z.string().nullish(),
  imageDigest: z.string().nullish(),
  params: z.record(z.unknown()).nullish(),
  attempt: z.number().int().nonnegative(),
  heartbeatAt: z.string().datetime().nullish(),
  errorCode: z.string().optional(),
  errorRetryable: z.boolean().optional(),
  errorCompletedSeeds: z.number().int().nonnegative().optional(),
});

const JobLogOutput = z.object({
  id: z.string(),
  level: z.enum(["info", "warn", "error"]),
  event: z.string(),
  message: z.string(),
  metadata: z.record(z.unknown()).nullable(),
  createdAt: z.string().datetime(),
});

/** Include a small queue/startup allowance on top of manifest compute time. */
function estimateEtaSeconds(
  numDesigns: number,
  secondsPerDesign: number,
  gpuType: string,
): number {
  const raw = Number.parseInt(process.env.MODAL_SEED_PARALLELISM ?? "", 10);
  const fallback = gpuType.toUpperCase() === "CPU" ? 4 : 2;
  const parallelism = Math.max(
    1,
    Math.min(8, Number.isFinite(raw) ? raw : fallback),
  );
  return (
    30 +
    Math.ceil(
      Math.max(0, secondsPerDesign) *
        Math.ceil(Math.max(0, numDesigns) / parallelism),
    )
  );
}

/**
 * Dev-mode switch: when true, the submit mutation synchronously marks the job
 * succeeded and persists fake Design rows instead of enqueueing. Defaults to
 * true if `MODAL_TOKEN_ID` is unset (typical local dev / no GPU credentials).
 */
function isDevMode(): boolean {
  const flag = process.env.WORKER_DEV_MODE;
  if (flag === "true") return true;
  if (flag === "false") return false;
  return !process.env.MODAL_TOKEN_ID;
}

function hasSystemModalCredentials(): boolean {
  return Boolean(process.env.MODAL_TOKEN_ID && process.env.MODAL_TOKEN_SECRET);
}

/**
 * Uploaded structures are addressed by their private R2 object key. Reject a
 * key outside the caller's org before any presigning, cost projection, or DB
 * write can occur. Non-R2 references (RCSB ids, raw structures, external
 * URLs) are intentionally left to the tool-specific input contract.
 */
function assertOwnedArtifactReference(
  value: unknown,
  orgId: string,
  label: string,
): void {
  if (typeof value !== "string" || !value.startsWith("orgs/")) return;

  const ownedPrefix = `orgs/${orgId}/`;
  if (
    !value.startsWith(ownedPrefix) ||
    value.length === ownedPrefix.length ||
    value.includes("..") ||
    value.includes("//")
  ) {
    throw new TRPCError({
      code: "BAD_REQUEST",
      message: `${label} artifact key is outside this organization`,
    });
  }
}

const ACTIVE_JOB_STATUSES = [
  "queued",
  "preparing",
  "running",
  "partial",
  "cancelling",
];

/**
 * Extract the GPU type + seconds-per-design from a Tool's JSONB `compute`
 * blob. Tolerates both `gpu` and `gpuType` keys (legacy and current schema
 * payloads coexist); falls back to A100-80GB / 120s when missing, matching
 * the cost calculator's defaults.
 */
function extractComputeProfile(compute: unknown): {
  gpuType: string;
  estSecondsPerDesign: number;
} {
  const c = (compute ?? {}) as {
    gpu?: unknown;
    gpuType?: unknown;
    estSecondsPerDesign?: unknown;
  };
  const gpuType =
    typeof c.gpuType === "string" && c.gpuType.length > 0
      ? c.gpuType
      : typeof c.gpu === "string" && c.gpu.length > 0
        ? c.gpu
        : DEFAULT_FALLBACK_GPU;
  const estSecondsPerDesign =
    typeof c.estSecondsPerDesign === "number" && c.estSecondsPerDesign > 0
      ? c.estSecondsPerDesign
      : DEFAULT_SECONDS_PER_DESIGN;
  return { gpuType, estSecondsPerDesign };
}

/**
 * Look up a tool's compute profile in RLS, then project the dollar cost.
 * Pure-ish helper hoisted out of the submit mutation so `previewCost` can
 * call it too. Typed against the full Context so it composes with the real
 * `withRlsUser` signature.
 *
 * The same row lookup also carries the tool's real `version`,
 * `adapterVersion`, and `imageDigest`, so we thread those out for provenance —
 * the submit handler stamps all three onto the created Job row instead of
 * hardcoded placeholders. Each is `null` only when the tool can't be resolved
 * or the catalog row carries no value for that field.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function projectCostFromTool(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ctx: any,
  userId: string,
  toolId: string,
  numDesigns: number,
): Promise<{
  estimate: ReturnType<typeof estimateJobCost>;
  version: string | null;
  adapterVersion: string | null;
  imageDigest: string | null;
  inputSchema: unknown;
  defaultParams: unknown;
}> {
  const row = await ctx.withRlsUser(ctx.prisma, userId, async (tx: unknown) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const client = tx as any;
    if (!client.tool?.findUnique) return null;
    return (await client.tool.findUnique({
      where: { id: toolId },
      select: {
        compute: true,
        version: true,
        adapterVersion: true,
        imageDigest: true,
        inputSchema: true,
        defaultParams: true,
      },
    })) as {
      compute?: unknown;
      version?: unknown;
      adapterVersion?: unknown;
      imageDigest?: unknown;
      inputSchema?: unknown;
      defaultParams?: unknown;
    } | null;
  });
  const profile = extractComputeProfile(row?.compute);
  const estimate = estimateJobCost({
    gpuType: profile.gpuType,
    estSecondsPerDesign: profile.estSecondsPerDesign,
    numSeeds: numDesigns,
  });
  const version =
    typeof row?.version === "string" && row.version.length > 0
      ? row.version
      : null;
  const adapterVersion =
    typeof row?.adapterVersion === "string" && row.adapterVersion.length > 0
      ? row.adapterVersion
      : null;
  const imageDigest =
    typeof row?.imageDigest === "string" && row.imageDigest.length > 0
      ? row.imageDigest
      : null;
  return {
    estimate,
    version,
    adapterVersion,
    imageDigest,
    inputSchema: row?.inputSchema,
    defaultParams: row?.defaultParams,
  };
}

async function hasOrgModalCredentials(ctx: {
  prisma: unknown;
  withRlsUser: <T>(
    prisma: unknown,
    userId: string,
    fn: (tx: unknown) => Promise<T>,
  ) => Promise<T>;
  auth: { userId: string; orgId: string };
}): Promise<boolean> {
  return ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx: unknown) => {
    const client = tx as {
      modalCredential?: {
        findUnique: (args: unknown) => Promise<unknown | null>;
      };
      $queryRawUnsafe?: <T = unknown>(
        query: string,
        ...values: unknown[]
      ) => Promise<T>;
    };
    if (client.modalCredential?.findUnique) {
      const row = await client.modalCredential.findUnique({
        where: { orgId: ctx.auth.orgId },
        select: { orgId: true },
      });
      return Boolean(row);
    }
    if (!client.$queryRawUnsafe) return false;
    const rows = await client.$queryRawUnsafe<Array<{ exists: boolean }>>(
      'SELECT EXISTS (SELECT 1 FROM modal_credentials WHERE org_id = $1::uuid) AS "exists"',
      ctx.auth.orgId,
    );
    return Boolean(rows?.[0]?.exists);
  });
}

/** Build a 60-residue plausible-looking sequence deterministically from a seed. */
function buildMockSequence(seed: number): string {
  // Standard 20 amino acids; biased slightly toward common residues.
  const aa = "ACDEFGHIKLMNPQRSTVWYAGLSV";
  let s = "";
  let x = (seed * 2654435761) >>> 0; // simple xorshift seed mixer
  for (let i = 0; i < 60; i++) {
    x = (x ^ (x << 13)) >>> 0;
    x = (x ^ (x >>> 17)) >>> 0;
    x = (x ^ (x << 5)) >>> 0;
    s += aa[x % aa.length];
  }
  return s;
}

/** Realistic-ish mock metrics for a dev-mode design row. */
function buildMockMetrics(seed: number): Record<string, unknown> {
  // Linear congruential for reproducibility per seed.
  const r = (n: number) => {
    const v = Math.sin(seed * 9301 + n * 49297) * 233280;
    return v - Math.floor(v);
  };
  const ipsae = 0.45 + r(1) * 0.4; // 0.45..0.85
  const dockq = 0.2 + r(2) * 0.45; // 0.20..0.65
  return {
    ipsae: Number(ipsae.toFixed(3)),
    dockq: Number(dockq.toFixed(3)),
    iptm: Number((ipsae * 0.95).toFixed(3)),
    plddt: Number((70 + r(3) * 20).toFixed(2)),
    runtimeSeconds: 12,
    sequence: buildMockSequence(seed),
    devStub: true,
  };
}

/**
 * Map a raw Prisma `jobs` row to the {@link JobSummarySchema} wire shape.
 * The schema columns are `tool`/`seedsRequested`/`seedsConsumed`; the wire
 * uses `toolId`/`numDesigns`/`completedDesigns`. Doing the rename here keeps
 * the rest of the API code path schema-faithful without leaking column names.
 */
function rowToJobSummary(row: Record<string, unknown>): {
  id: string;
  projectId: string | null;
  toolId: string;
  status: string;
  submittedAt: string;
  startedAt?: string;
  finishedAt?: string;
  numDesigns: number;
  completedDesigns: number;
  errorMessage?: string;
} {
  const submittedAt = row.submittedAt;
  const startedAt = row.startedAt;
  const completedAt = row.completedAt;
  const error = row.error as { message?: string } | undefined;
  return {
    id: String(row.id),
    projectId: typeof row.projectId === "string" ? row.projectId : null,
    toolId: String(row.tool ?? row.toolId ?? ""),
    status: String(row.status ?? "queued"),
    submittedAt:
      submittedAt instanceof Date
        ? submittedAt.toISOString()
        : String(submittedAt),
    startedAt:
      startedAt instanceof Date
        ? startedAt.toISOString()
        : startedAt
          ? String(startedAt)
          : undefined,
    finishedAt:
      completedAt instanceof Date
        ? completedAt.toISOString()
        : completedAt
          ? String(completedAt)
          : undefined,
    numDesigns: Number(row.seedsRequested ?? row.numDesigns ?? 0),
    completedDesigns: Number(row.seedsConsumed ?? row.completedDesigns ?? 0),
    errorMessage: error?.message,
  };
}

/**
 * Map a raw `jobs` row to the {@link JobDetailOutput} shape — the summary
 * plus the provenance columns (`tool_version` / `adapter_version` /
 * `image_digest`) and the verbatim submitted `params`. Used by `jobs.get`
 * so the detail UI can render a genuinely reproducible provenance view.
 */
function rowToJobDetail(
  row: Record<string, unknown>,
): z.infer<typeof JobDetailOutput> {
  const summary = rowToJobSummary(row);
  const error =
    row.error && typeof row.error === "object"
      ? (row.error as Record<string, unknown>)
      : null;
  const toStr = (v: unknown): string | null =>
    typeof v === "string" && v.length > 0 ? v : null;
  return {
    ...summary,
    toolVersion: toStr(row.toolVersion),
    adapterVersion: toStr(row.adapterVersion),
    imageDigest: toStr(row.imageDigest),
    attempt: Number.isInteger(row.attempt) ? Number(row.attempt) : 0,
    heartbeatAt:
      row.heartbeatAt instanceof Date
        ? row.heartbeatAt.toISOString()
        : toStr(row.heartbeatAt),
    errorCode: typeof error?.code === "string" ? error.code : undefined,
    errorRetryable:
      typeof error?.retryable === "boolean" ? error.retryable : undefined,
    errorCompletedSeeds:
      typeof error?.completedSeeds === "number" &&
      Number.isInteger(error.completedSeeds)
        ? error.completedSeeds
        : undefined,
    params:
      row.params && typeof row.params === "object"
        ? (row.params as Record<string, unknown>)
        : null,
  } as z.infer<typeof JobDetailOutput>;
}

export const jobsRouter = router({
  submit: protectedProcedure
    .meta({
      openapi: {
        method: "POST",
        path: "/jobs",
        tags: ["jobs"],
        summary: "Submit a new design job",
        protect: true,
      },
    })
    .input(JobSubmissionSchema)
    .output(SubmitOutput)
    .mutation(async ({ ctx, input }) => {
      const auth = ctx.auth;
      const { toolId, request, workflowId } = input;
      const workflow = getPapercraneWorkflow(workflowId);
      const executionStages = workflow?.stages ?? [
        { toolId, label: toolId, params: {} },
      ];
      if (workflow && executionStages[0]?.toolId !== toolId) {
        throw new TRPCError({
          code: "BAD_REQUEST",
          message: `workflow '${workflow.id}' must be submitted with entry tool '${executionStages[0]?.toolId}'`,
        });
      }
      const executionToolId = workflow ? workflowToolId(workflow) : toolId;

      // 1. Tier allowlist check — cheap, no DB hop.
      for (const stage of executionStages) {
        if (!isToolAllowedForTier(auth.tier, stage.toolId)) {
          throw new TRPCError({
            code: "FORBIDDEN",
            message: `tool '${stage.toolId}' not allowed for tier '${auth.tier}'`,
          });
        }

        // Catalog visibility is not permission to spend compute. Every stage
        // in a trusted workflow must be runnable before any spend is reserved.
        if (!isToolRunnable(stage.toolId)) {
          throw new TRPCError({
            code: "PRECONDITION_FAILED",
            message: `tool '${stage.toolId}' is not yet runnable`,
          });
        }
      }

      // 1a. Per-job seed cap (beta guardrail) — cheap, no DB hop, fails fast
      //     before any cost projection or DB write. The worker now uses bounded
      //     fan-out, but a cap still limits spend, artifact churn, and the tail
      //     of slow lanes under Modal's timeout. See MAX_SEEDS_PER_JOB above.
      const seedCap = maxSeedsPerJob();
      const seedCount = request.seeds.length;
      if (seedCount > seedCap) {
        throw new TRPCError({
          code: "BAD_REQUEST",
          message: `Requested ${seedCount} seeds exceeds the current per-job limit of ${seedCap}. Split the campaign into multiple jobs.`,
        });
      }

      // 1b. Resolve target/project identity under RLS. This both preserves
      // provenance on the Job row and gives downstream target-conditioned
      // scoring a verified identity instead of guessing from display text.
      const requestToolParams =
        request.toolParams && typeof request.toolParams === "object"
          ? (request.toolParams as Record<string, unknown>)
          : {};

      // Canonical inputs normally live at the request root, but validate the
      // legacy nested aliases too because the worker accepts both shapes.
      // Ligand uploads are currently tool-specific and therefore nested.
      assertOwnedArtifactReference(request.targetPdb, auth.orgId, "target");
      assertOwnedArtifactReference(request.partnerPdb, auth.orgId, "partner");
      assertOwnedArtifactReference(
        requestToolParams.targetPdb,
        auth.orgId,
        "target",
      );
      assertOwnedArtifactReference(
        requestToolParams.partnerPdb,
        auth.orgId,
        "partner",
      );
      assertOwnedArtifactReference(
        requestToolParams.ligand_sdf,
        auth.orgId,
        "ligand",
      );

      const targetIdRaw = requestToolParams.targetId;
      const projectIdRaw = requestToolParams.projectId;
      const requestedTargetId =
        typeof targetIdRaw === "string" && targetIdRaw.length > 0
          ? targetIdRaw
          : null;
      const requestedProjectId =
        typeof projectIdRaw === "string" && projectIdRaw.length > 0
          ? projectIdRaw
          : null;
      const uuidSchema = z.string().uuid();
      if (
        requestedTargetId &&
        !uuidSchema.safeParse(requestedTargetId).success
      ) {
        throw new TRPCError({
          code: "BAD_REQUEST",
          message: "invalid targetId",
        });
      }
      if (
        requestedProjectId &&
        !uuidSchema.safeParse(requestedProjectId).success
      ) {
        throw new TRPCError({
          code: "BAD_REQUEST",
          message: "invalid projectId",
        });
      }

      const pdbCandidate =
        typeof request.targetPdb === "string" ? request.targetPdb.trim() : "";
      const pdbId = /^[A-Za-z0-9]{4}$/.test(pdbCandidate)
        ? pdbCandidate.toUpperCase()
        : null;
      const resolvedIdentity = await ctx.withRlsUser(
        ctx.prisma,
        auth.userId,
        async (tx) => {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const client = tx as any;
          const [target, project] = await Promise.all([
            requestedTargetId || pdbId
              ? client.target?.findFirst?.({
                  where: requestedTargetId
                    ? { id: requestedTargetId, orgId: auth.orgId }
                    : { orgId: auth.orgId, pdbId },
                  select: { id: true, projectId: true, hotspots: true },
                  orderBy: { createdAt: "desc" },
                })
              : null,
            requestedProjectId
              ? client.project?.findFirst?.({
                  where: { id: requestedProjectId, orgId: auth.orgId },
                  select: { id: true },
                })
              : null,
          ]);
          return { target: target ?? null, project: project ?? null } as {
            target: {
              id: string;
              projectId?: string | null;
              hotspots?: unknown;
            } | null;
            project: { id: string } | null;
          };
        },
      );
      if (requestedTargetId && !resolvedIdentity.target) {
        throw new TRPCError({ code: "NOT_FOUND", message: "target not found" });
      }
      if (requestedProjectId && !resolvedIdentity.project) {
        throw new TRPCError({
          code: "NOT_FOUND",
          message: "project not found",
        });
      }
      if (
        requestedProjectId &&
        resolvedIdentity.target?.projectId &&
        resolvedIdentity.target.projectId !== requestedProjectId
      ) {
        throw new TRPCError({
          code: "BAD_REQUEST",
          message: "target does not belong to the requested project",
        });
      }
      const resolvedTargetId = resolvedIdentity.target?.id ?? null;
      const resolvedProjectId =
        resolvedIdentity.project?.id ??
        resolvedIdentity.target?.projectId ??
        null;

      // Auto-include hotspots saved on the resolved Target only when the
      // caller did not already pass an explicit set.
      const callerHotspots = (request.hotspots ?? []) as unknown[];
      const callerSuppliedHotspots =
        Array.isArray(callerHotspots) && callerHotspots.length > 0;
      if (!callerSuppliedHotspots) {
        const savedHotspots = resolvedIdentity.target?.hotspots ?? null;
        // Normalise legacy single-object shape into an array before merging.
        const normalised = Array.isArray(savedHotspots)
          ? (savedHotspots as unknown[])
          : savedHotspots &&
              typeof savedHotspots === "object" &&
              "chain" in (savedHotspots as object)
            ? [savedHotspots as unknown]
            : [];
        if (normalised.length > 0) {
          (request as { hotspots?: unknown }).hotspots = normalised;
        }
      }

      // 2. Seed quota check + job insert in a single RLS transaction so
      //    we don't race against concurrent submissions from the same org.
      //    Prisma schema fields (see packages/db/prisma/schema.prisma):
      //      tool, toolVersion, params (JsonB), seedsRequested, expiresAt
      //    The tRPC contract uses `toolId/numDesigns/completedDesigns`, so we
      //    map between the wire shape and the row shape here.
      const requestedSeeds = request.seeds.length;
      const retentionDaysFallback = 7;
      const expiresAt = new Date(
        Date.now() + retentionDaysFallback * 24 * 60 * 60 * 1000,
      );

      // Project the dollar cost up-front (also used for the GpuSpend row and
      // the budget check). Reads the tool row in RLS — same predicate the
      // submit transaction uses, so an unauthorized caller can never preview
      // a cost for a tool they couldn't otherwise see.
      const stageProjections = await Promise.all(
        executionStages.map((stage) =>
          projectCostFromTool(
            ctx,
            auth.userId,
            stage.toolId,
            requestedSeeds,
          ),
        ),
      );
      const primaryProjection = stageProjections[0]!;
      const costEstimate =
        stageProjections.length === 1
          ? primaryProjection.estimate
          : {
              usd: stageProjections.reduce(
                (sum, projection) => sum.add(projection.estimate.usd),
                new Prisma.Decimal(0),
              ),
              breakdown: {
                ...primaryProjection.estimate.breakdown,
                gpuType: "multi-stage",
                fallbackUsed: stageProjections.some(
                  (projection) => projection.estimate.breakdown.fallbackUsed,
                ),
                pricePerSecondUsd: Math.max(
                  ...stageProjections.map(
                    (projection) =>
                      projection.estimate.breakdown.pricePerSecondUsd,
                  ),
                ),
                secondsPerDesign: stageProjections.reduce(
                  (sum, projection) =>
                    sum + projection.estimate.breakdown.secondsPerDesign,
                  0,
                ),
                perSeedUsd: stageProjections.reduce(
                  (sum, projection) =>
                    sum + projection.estimate.breakdown.perSeedUsd,
                  0,
                ),
              },
            };
      const resolvedToolVersion = workflow
        ? executionStages
            .map(
              (stage, index) =>
                `${stage.toolId}@${stageProjections[index]?.version ?? "0.0.0"}`,
            )
            .join(" → ")
        : primaryProjection.version;
      const resolvedAdapterVersion = stageProjections
        .map((projection) => projection.adapterVersion)
        .filter((value): value is string => Boolean(value))
        .join(" → ") || null;
      const resolvedImageDigest = stageProjections
        .map((projection) => projection.imageDigest)
        .filter((value): value is string => Boolean(value))
        .join(" → ") || null;

      for (const [index, stage] of executionStages.entries()) {
        const projection = stageProjections[index]!;
        const suppliedParams = {
          ...stage.params,
          ...(index === 0 && request.toolParams
            ? (request.toolParams as Record<string, unknown>)
            : {}),
        };
        const parameterValidation = validateToolParameters(
          projection.inputSchema,
          projection.defaultParams,
          suppliedParams,
        );
        if (!parameterValidation.valid) {
          throw new TRPCError({
            code: parameterValidation.configurationError
              ? "PRECONDITION_FAILED"
              : "BAD_REQUEST",
            message: `${stage.label}: ${parameterValidation.message ?? "Invalid tool parameters."}`,
          });
        }
      }

      const storedRequest = workflow
        ? {
            ...request,
            _papercraneWorkflow: {
              id: workflow.id,
              version: 1,
              stages: executionStages,
            },
          }
        : request;

      const row = await ctx.withRlsUser(ctx.prisma, auth.userId, async (tx) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const client = tx as any;
        const [org, flags, activeJobs] = await Promise.all([
          client.organization?.findUnique?.({
            where: { id: auth.orgId },
            select: {
              seedsQuota: true,
              seedsUsed: true,
              gpuSpendCapUsd: true,
              gpuSpendUsd: true,
            },
          }),
          client.featureFlag?.findUnique?.({
            where: { orgId: auth.orgId },
            select: { maxConcurrent: true, onCap: true },
          }),
          client.job?.findMany?.({
            where: { orgId: auth.orgId, status: { in: ACTIVE_JOB_STATUSES } },
            select: { seedsRequested: true, seedsConsumed: true },
          }),
        ]);
        const maxConcurrent = Number(flags?.maxConcurrent ?? 2);
        const activeCount = Array.isArray(activeJobs) ? activeJobs.length : 0;
        if (maxConcurrent > 0 && activeCount >= maxConcurrent) {
          throw new TRPCError({
            code: "FORBIDDEN",
            message: `concurrency limit reached: ${activeCount}/${maxConcurrent} jobs already active`,
          });
        }
        const pendingSeeds = Array.isArray(activeJobs)
          ? activeJobs.reduce((sum, job) => {
              const requested = Number(job.seedsRequested ?? 0);
              const consumed = Number(job.seedsConsumed ?? 0);
              return sum + Math.max(0, requested - consumed);
            }, 0)
          : 0;
        const quota = Number(org?.seedsQuota ?? 0);
        const used = Number(org?.seedsUsed ?? 0);
        const blocksAtCap = flags?.onCap !== "overage";
        if (
          blocksAtCap &&
          quota > 0 &&
          used + pendingSeeds + requestedSeeds > quota
        ) {
          throw new TRPCError({
            code: "FORBIDDEN",
            message: `seed allocation exhausted: need ${requestedSeeds}, available ${Math.max(
              0,
              quota - used - pendingSeeds,
            )}`,
          });
        }

        // ── GPU spend cap (private-beta hard cap) ─────────────────────────
        // Defaults to $50/org via the schema default. The cap is per-org so
        // founders can raise it for individual teams without a code change.
        const cap = new Prisma.Decimal(org?.gpuSpendCapUsd ?? 50);
        const current = new Prisma.Decimal(org?.gpuSpendUsd ?? 0);
        const projected = current.add(costEstimate.usd);
        if (projected.gt(cap)) {
          const remaining = Prisma.Decimal.max(cap.sub(current), 0);
          throw new TRPCError({
            code: "FORBIDDEN",
            message: `GPU spend cap reached. This job would cost $${costEstimate.usd.toFixed(
              2,
            )} but only $${remaining.toFixed(2)} remains in your $${cap.toFixed(
              2,
            )} cap. Contact founders@papercrane.bio for an increase.`,
          });
        }

        const created = (await client.job.create({
          data: {
            orgId: auth.orgId,
            projectId: resolvedProjectId,
            targetId: resolvedTargetId,
            tool: executionToolId,
            // Real provenance: stamp the tool's actual version (from the same
            // RLS lookup that computed the cost). Falls back to '0.0.0' only
            // when the tool can't be resolved / carries no version.
            toolVersion: resolvedToolVersion ?? "0.0.0",
            // Reproducibility provenance: the resolved adapter version and the
            // container image digest the run pins to. Both stay null when the
            // catalog row carries no value (image digests are placeholder until
            // the tool's image is built).
            adapterVersion: resolvedAdapterVersion ?? null,
            imageDigest: resolvedImageDigest ?? null,
            params: storedRequest as unknown as Record<string, unknown>,
            seedsRequested: requestedSeeds,
            queueTier: auth.tier,
            status: "queued",
            expiresAt,
          },
        })) as { id: string; submittedAt?: Date; seedsRequested?: number };

        // Atomically debit the org's running total AND insert the ledger row
        // in the same transaction so the next budget check sees the new
        // total. We do the increment via raw SQL rather than `{ increment }`
        // so it composes against a Decimal column without Prisma silently
        // coercing.
        await client.$executeRawUnsafe?.(
          "UPDATE organizations SET gpu_spend_usd = gpu_spend_usd + $1::numeric WHERE id = $2::uuid",
          costEstimate.usd.toString(),
          auth.orgId,
        );

        await client.gpuSpend?.create?.({
          data: {
            orgId: auth.orgId,
            jobId: created.id,
            tool: executionToolId,
            gpuType: costEstimate.breakdown.gpuType,
            estimatedUsd: costEstimate.usd,
          },
        });

        return created;
      });

      // 3a. Dev-mode short-circuit: no Redis, no Modal — synchronously mark
      //     the job succeeded and persist fake Design rows so the UI has
      //     something to render. Gated by WORKER_DEV_MODE / MODAL_TOKEN_ID.
      const hasByocModal = await hasOrgModalCredentials(ctx as never);
      if (isDevMode() && !hasByocModal && !hasSystemModalCredentials()) {
        const numDesigns = request.numDesigns;
        const count = Math.min(5, Math.max(1, numDesigns));
        await ctx.withRlsUser(ctx.prisma, auth.userId, async (tx) => {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const client = tx as any;
          // Flip the job to succeeded with timing fields set.
          const now = new Date();
          await client.job.update({
            where: { id: row.id },
            data: {
              status: "succeeded",
              startedAt: now,
              completedAt: now,
              seedsConsumed: count,
            },
          });
          // Persist 5 fake designs (or numDesigns, whichever is smaller).
          const rows = Array.from({ length: count }, (_v, i) => {
            const seed = i + 1;
            return {
              jobId: row.id,
              orgId: auth.orgId,
              seed,
              metrics: buildMockMetrics(seed),
              artifactKey: `dev/${row.id}/seed-${seed}.cif`,
              rank: i + 1,
              provenance: "synthetic",
            };
          });
          await client.design.createMany({ data: rows });

          // Synthetic previews do not consume GPU budget. Submission reserved
          // the estimate transactionally, so reconcile it to zero before
          // returning the completed preview.
          await client.gpuSpend?.updateMany?.({
            where: { jobId: row.id },
            data: { actualUsd: new Prisma.Decimal(0), secondsActual: 0 },
          });
          await client.$executeRawUnsafe?.(
            "UPDATE organizations SET gpu_spend_usd = GREATEST(0, gpu_spend_usd - $1::numeric) WHERE id = $2::uuid",
            costEstimate.usd.toString(),
            auth.orgId,
          );
        });

        const submittedAt =
          row.submittedAt instanceof Date
            ? row.submittedAt.toISOString()
            : String(row.submittedAt);
        return {
          id: row.id,
          toolId: executionToolId,
          status: "succeeded" as const,
          submittedAt,
          numDesigns:
            (row as { seedsRequested?: number }).seedsRequested ??
            request.numDesigns,
          completedDesigns: count,
          etaSeconds: 0,
        };
      }

      // 3b. Prod path: enqueue onto the tier queue. The worker picks it up.
      await ctx.withRlsUser(ctx.prisma, auth.userId, async (tx) => {
        const client = tx as unknown as {
          job: { update: (args: unknown) => Promise<unknown> };
        };
        await client.job.update({
          where: { id: row.id },
          data: { gpuBackend: "modal" },
        });
      });
      const queueName = JOB_QUEUE_NAMES[auth.tier];
      await ctx.enqueueJob(queueName, {
        jobId: row.id,
        toolId: executionToolId,
        orgId: auth.orgId,
      });

      const submittedAt =
        row.submittedAt instanceof Date
          ? row.submittedAt.toISOString()
          : String(row.submittedAt);

      return {
        id: row.id,
        toolId: executionToolId,
        status: "queued" as const,
        submittedAt,
        // Map row.seedsRequested -> wire numDesigns; freshly-queued rows have 0 designs.
        numDesigns:
          (row as { seedsRequested?: number }).seedsRequested ??
          request.numDesigns,
        completedDesigns: 0,
        etaSeconds: estimateEtaSeconds(
          requestedSeeds,
          costEstimate.breakdown.secondsPerDesign,
          costEstimate.breakdown.gpuType,
        ),
      };
    }),

  get: protectedProcedure
    .meta({
      openapi: {
        method: "GET",
        path: "/jobs/{id}",
        tags: ["jobs"],
        summary: "Get a job by id",
        protect: true,
      },
    })
    .input(z.object({ id: z.string().min(1) }))
    .output(JobDetailOutput)
    .query(async ({ ctx, input }) => {
      const row = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as {
            job: { findFirst: (args: unknown) => Promise<unknown | null> };
          };
          return client.job.findFirst({
            where: { id: input.id, orgId: ctx.auth!.orgId },
          });
        },
      );
      if (!row)
        throw new TRPCError({ code: "NOT_FOUND", message: "job not found" });
      return rowToJobDetail(row as Record<string, unknown>);
    }),

  list: protectedProcedure
    .meta({
      openapi: {
        method: "GET",
        path: "/jobs",
        tags: ["jobs"],
        summary: "List jobs for the caller’s org",
        protect: true,
      },
    })
    .input(
      z
        .object({
          projectId: z.string().uuid().optional(),
          status: z
            .enum([
              "queued",
              "preparing",
              "running",
              "partial",
              "succeeded",
              "failed",
              "cancelling",
              "cancelled",
              "purged",
            ])
            .optional(),
          limit: z.number().int().positive().max(200).optional(),
        })
        .strict(),
    )
    .output(z.object({ items: z.array(JobSummarySchema) }))
    .query(async ({ ctx, input }) => {
      const items = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as {
            job: { findMany: (args: unknown) => Promise<unknown[]> };
          };
          return client.job.findMany({
            where: {
              orgId: ctx.auth!.orgId,
              ...(input.status ? { status: input.status } : {}),
              ...(input.projectId ? { projectId: input.projectId } : {}),
            },
            orderBy: { submittedAt: "desc" },
            take: input.limit ?? 50,
          });
        },
      );
      return {
        items: (items as Record<string, unknown>[]).map((r) =>
          rowToJobSummary(r),
        ) as z.infer<typeof JobSummarySchema>[],
      };
    }),

  logs: protectedProcedure
    .meta({
      openapi: {
        method: "GET",
        path: "/jobs/{id}/logs",
        tags: ["jobs"],
        summary: "Read durable, redacted job logs",
        protect: true,
      },
    })
    .input(
      z.object({
        id: z.string().min(1),
        limit: z.number().int().positive().max(500).optional(),
        after: z.string().datetime().optional(),
      }),
    )
    .output(z.object({ items: z.array(JobLogOutput) }))
    .query(async ({ ctx, input }) => {
      const rows = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as {
            job: {
              findFirst: (args: unknown) => Promise<{ id: string } | null>;
            };
            jobLog: {
              findMany: (args: unknown) => Promise<
                Array<{
                  id: string;
                  level: string;
                  event: string;
                  message: string;
                  metadata: unknown;
                  createdAt: Date;
                }>
              >;
            };
          };
          const job = await client.job.findFirst({
            where: { id: input.id, orgId: ctx.auth!.orgId },
            select: { id: true },
          });
          if (!job) return null;
          return client.jobLog.findMany({
            where: {
              jobId: job.id,
              ...(input.after
                ? { createdAt: { gte: new Date(input.after) } }
                : {}),
            },
            orderBy: [{ createdAt: "asc" }, { id: "asc" }],
            take: input.limit ?? 200,
          });
        },
      );
      if (!rows) {
        throw new TRPCError({ code: "NOT_FOUND", message: "job not found" });
      }
      return {
        items: rows.map((row) => ({
          id: row.id,
          level: row.level as "info" | "warn" | "error",
          event: row.event,
          message: row.message,
          metadata:
            row.metadata &&
            typeof row.metadata === "object" &&
            !Array.isArray(row.metadata)
              ? (row.metadata as Record<string, unknown>)
              : null,
          createdAt: row.createdAt.toISOString(),
        })),
      };
    }),

  /**
   * Preview the dollar cost of a job BEFORE the user submits it. The submit
   * form calls this on debounce as the user edits tool / numDesigns; the
   * server returns both the estimate and the org's current spend so the UI
   * can render the "$X remaining in your $50 cap" line and disable the
   * submit button when the next job would exceed the cap.
   *
   * The check is read-only and tolerant of unknown tool ids — we surface a
   * fallback estimate (A100-80GB / 120s) rather than refusing the preview,
   * so the user always sees *some* number.
   */
  previewCost: protectedProcedure
    .meta({
      openapi: {
        method: "POST",
        path: "/jobs/preview-cost",
        tags: ["jobs"],
        summary: "Estimate dollar cost of a job before submission",
        protect: true,
      },
    })
    .input(
      z.object({
        tool: z.string().min(1),
        workflowId: z
          .enum([
            "binder-screen",
            "binder-standard",
            "binder-high-confidence",
          ])
          .optional(),
        numDesigns: z.number().int().positive().max(1024),
      }),
    )
    .output(
      z.object({
        estimatedUsd: z.number().nonnegative(),
        currentSpendUsd: z.number().nonnegative(),
        capUsd: z.number().nonnegative(),
        remainingUsd: z.number().nonnegative(),
        wouldExceed: z.boolean(),
        breakdown: z.object({
          gpuType: z.string(),
          fallbackUsed: z.boolean(),
          pricePerSecondUsd: z.number().nonnegative(),
          secondsPerDesign: z.number().nonnegative(),
          numSeeds: z.number().int().nonnegative(),
          perSeedUsd: z.number().nonnegative(),
        }),
      }),
    )
    .query(async ({ ctx, input }) => {
      const auth = ctx.auth;
      const workflow = getPapercraneWorkflow(input.workflowId);
      const stageIds = workflow
        ? workflow.stages.map((stage) => stage.toolId)
        : [input.tool];
      const estimates = await Promise.all(
        stageIds.map((toolId) =>
          projectCostFromTool(
            ctx,
            auth.userId,
            toolId,
            input.numDesigns,
          ),
        ),
      );
      const first = estimates[0]!.estimate;
      const estimate =
        estimates.length === 1
          ? first
          : {
              usd: estimates.reduce(
                (sum, item) => sum.add(item.estimate.usd),
                new Prisma.Decimal(0),
              ),
              breakdown: {
                ...first.breakdown,
                gpuType: "multi-stage",
                fallbackUsed: estimates.some(
                  (item) => item.estimate.breakdown.fallbackUsed,
                ),
                pricePerSecondUsd: Math.max(
                  ...estimates.map(
                    (item) => item.estimate.breakdown.pricePerSecondUsd,
                  ),
                ),
                secondsPerDesign: estimates.reduce(
                  (sum, item) =>
                    sum + item.estimate.breakdown.secondsPerDesign,
                  0,
                ),
                perSeedUsd: estimates.reduce(
                  (sum, item) => sum + item.estimate.breakdown.perSeedUsd,
                  0,
                ),
              },
            };

      const org = await ctx.withRlsUser(ctx.prisma, auth.userId, async (tx) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const client = tx as any;
        return (await client.organization?.findUnique?.({
          where: { id: auth.orgId },
          select: { gpuSpendCapUsd: true, gpuSpendUsd: true },
        })) as {
          gpuSpendCapUsd?: Prisma.Decimal | string | number;
          gpuSpendUsd?: Prisma.Decimal | string | number;
        } | null;
      });
      const cap = new Prisma.Decimal(org?.gpuSpendCapUsd ?? 50);
      const current = new Prisma.Decimal(org?.gpuSpendUsd ?? 0);
      const remaining = Prisma.Decimal.max(cap.sub(current), 0);
      const wouldExceed = current.add(estimate.usd).gt(cap);

      return {
        estimatedUsd: Number(estimate.usd.toString()),
        currentSpendUsd: Number(current.toString()),
        capUsd: Number(cap.toString()),
        remainingUsd: Number(remaining.toString()),
        wouldExceed,
        breakdown: estimate.breakdown,
      };
    }),

  cancel: protectedProcedure
    .meta({
      openapi: {
        method: "POST",
        path: "/jobs/{jobId}/cancel",
        tags: ["jobs"],
        summary: "Request cancellation of a running job",
        protect: true,
      },
    })
    .input(z.object({ jobId: z.string().min(1) }))
    .output(JobSummarySchema)
    .mutation(async ({ ctx, input }) => {
      const row = await ctx.withRlsUser(
        ctx.prisma,
        ctx.auth.userId,
        async (tx) => {
          const client = tx as unknown as {
            $executeRawUnsafe: (query: string, ...args: unknown[]) => Promise<number>;
            job: {
              updateMany: (args: {
                where: Record<string, unknown>;
                data: Record<string, unknown>;
              }) => Promise<{ count: number }>;
              findFirst: (args: { where: Record<string, unknown> }) => Promise<Record<string, unknown> | null>;
            };
          };
          const where = { id: input.jobId, orgId: ctx.auth!.orgId };
          // Queued work has no provider to stop. Complete cancellation even
          // if the worker is offline, with a status guard against a claim race.
          const cancelledQueued = await client.job.updateMany({
            where: { ...where, status: "queued" },
            data: { status: "cancelled", completedAt: new Date() },
          });
          if (cancelledQueued.count > 0) {
            // Release unstarted compute reservations once, in the same
            // transaction as cancellation. No live worker is required.
            await client.$executeRawUnsafe(
              `WITH released AS (
                UPDATE gpu_spends SET actual_usd = 0, updated_at = NOW()
                WHERE job_id = $1::uuid AND org_id = $2::uuid AND actual_usd IS NULL
                RETURNING estimated_usd
              ) UPDATE organizations
                SET gpu_spend_usd = GREATEST(0, gpu_spend_usd - COALESCE((SELECT SUM(estimated_usd) FROM released), 0))
                WHERE id = $2::uuid`,
              input.jobId, ctx.auth!.orgId,
            );
          }
          await client.job.updateMany({
            where: { ...where, status: { in: ["preparing", "running"] } },
            data: { status: "cancelling" },
          });
          const job = await client.job.findFirst({ where });
          if (!job) throw new TRPCError({ code: "NOT_FOUND", message: "Job not found" });
          return job;
        },
      );
      // Publish outside the transaction: we want the DB commit to win before
      // the worker acts on the signal.
      if (row.status === "cancelling") await ctx.publishCancel(input.jobId);
      return rowToJobSummary(row as Record<string, unknown>) as z.infer<
        typeof JobSummarySchema
      >;
    }),
});
