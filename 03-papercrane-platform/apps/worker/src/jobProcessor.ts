/**
 * The single entry point BullMQ calls per job.
 *
 * Responsibilities (plan 01 §5):
 *   1. claim      → transition queued → preparing
 *   2. prepare    → load job row, resolve manifest, call provider.spawnJob
 *   3. stream     → transition preparing → running, then iterate provider seeds:
 *                     - check cancellation between seeds
 *                     - persist design row + seeds_consumed in a single tx
 *                     - publish design event + progress event
 *   4. complete   → transition running → succeeded (or cancelling → cancelled)
 *   5. fail       → on provider error, classify user vs infra, transition → failed,
 *                   emit error event with retryable flag
 *
 * Tests cover each outcome independently.
 */

import type { WorkerContext } from './context';
import type { JobEvent, Tier } from '@papercrane/jobs';
import {
  designEvent,
  errorEvent,
  progressEvent,
  statusEvent,
  INFRA_ERROR_CODES,
  USER_ERROR_CODES,
} from '@papercrane/jobs';
import { actualCostFromModalSeconds } from '@papercrane/billing';
import { Prisma } from '@papercrane/db';
import { getPapercraneWorkflow } from '@papercrane/types';
import type {
  Provider,
  ProviderSeedResult,
  ProviderSpawnInputs,
  ProviderSpawnResult,
} from './providers/types';
import { ModalProvider } from './providers/modal';
import { loadOrgModalCredentials } from './providers/modalCredentials';
import { validateMetrics } from './metrics/validate';
import { persistJobEvent } from './jobLogs';

const INFRA_SET = new Set<string>(INFRA_ERROR_CODES);
const USER_SET = new Set<string>(USER_ERROR_CODES);

export interface ProcessJobInput {
  jobId: string;
  /** Queue identity is authoritative; the row copy enables stale recovery. */
  tier?: Tier;
  /** 1-indexed BullMQ attempt. Persisted to fence stale workers. */
  attempt?: number;
}

export interface ProcessJobResult {
  outcome: 'succeeded' | 'failed' | 'cancelled';
  seedsCompleted: number;
  retryable?: boolean;
  errorCode?: string;
  errorMessage?: string;
}

export async function processJob(
  ctx: WorkerContext,
  input: ProcessJobInput,
): Promise<ProcessJobResult> {
  const { jobId } = input;
  const attempt = input.attempt ?? 1;
  const log = ctx.logger.child({ jobId });

  // ---- 1. Claim ----
  const stopBeforeClaim = async (): Promise<ProcessJobResult | null> => {
    const pending = await ctx.prisma.job.findUnique({ where: { id: jobId } });
    if (!pending) return { outcome: 'failed', seedsCompleted: 0, retryable: false, errorMessage: 'Job not found' };
    if (pending.status === 'cancelling') {
      await ctx.transitionJob(jobId, 'cancelled');
      await publish(ctx, jobId, statusEvent('cancelled'));
      await reconcileGpuSpend(ctx, { jobId, orgId: pending.orgId, numSeeds: pending.seedsRequested, seedsCompleted: pending.seedsConsumed, outcome: 'cancelled' });
      ctx.cancellation.clear(jobId);
      return { outcome: 'cancelled', seedsCompleted: pending.seedsConsumed };
    }
    if (['cancelled', 'succeeded', 'partial', 'failed', 'purged'].includes(pending.status)) {
      if (pending.status === 'cancelled' && !pending.startedAt) {
        await reconcileGpuSpend(ctx, { jobId, orgId: pending.orgId, numSeeds: pending.seedsRequested, seedsCompleted: pending.seedsConsumed, outcome: 'cancelled' });
      }
      return { outcome: pending.status === 'cancelled' ? 'cancelled' : pending.status === 'succeeded' ? 'succeeded' : 'failed', seedsCompleted: pending.seedsConsumed, retryable: false };
    }
    return null;
  };
  const stopped = await stopBeforeClaim();
  if (stopped) return stopped;
  try {
    await ctx.transitionJob(jobId, 'preparing');
  } catch (error) {
    const cancelledDuringClaim = await stopBeforeClaim();
    if (cancelledDuringClaim) return cancelledDuringClaim;
    throw error;
  }
  await publish(ctx, jobId, statusEvent('preparing'));

  // ---- 2. Load job row ----
  const job = await ctx.prisma.job.findUnique({
    where: { id: jobId },
    include: {
      target: { select: { artifactKey: true, pdbId: true } },
      designs: { select: { seed: true } },
    },
  });
  if (!job) {
    log.error('job row disappeared after claim');
    await ctx.transitionJob(jobId, 'failed', {
      reason: 'job row not found after claim',
      error: { code: 'NOT_FOUND', message: 'job row not found', retryable: false },
    });
    await publish(ctx, jobId, errorEvent(false, 'job row not found'));
    return { outcome: 'failed', seedsCompleted: 0, retryable: false, errorMessage: 'not found' };
  }

  const existingSeeds = new Set(
    ((job as { designs?: Array<{ seed: number }> }).designs ?? []).map((design) => design.seed),
  );
  const requestedSeeds = resolveRequestedSeeds(
    (job as { params: unknown }).params,
    (job as { seedsRequested: number }).seedsRequested,
  );
  const missingSeeds = requestedSeeds.filter((seed) => !existingSeeds.has(seed));

  // Keep the persisted progress counter derived from the source of truth and
  // register the current attempt before touching the provider. The heartbeat
  // is renewed even while a model is quiet between seed results.
  const ownsAttempt = await registerAttempt(ctx, jobId, attempt, existingSeeds.size);
  if (!ownsAttempt) {
    log.warn({ attempt }, 'ignoring superseded worker attempt');
    return {
      outcome: 'failed',
      seedsCompleted: existingSeeds.size,
      retryable: false,
      errorCode: 'WORKER_STALLED',
      errorMessage: `worker attempt ${attempt} was superseded`,
    };
  }
  const stopHeartbeat = startHeartbeat(ctx, jobId, attempt);
  const finish = (result: ProcessJobResult): ProcessJobResult => {
    stopHeartbeat();
    return result;
  };

  // ---- 3. Spawn provider ----
  const providerName = (job as { gpuBackend?: string }).gpuBackend ?? 'modal';
  let provider: Provider;
  try {
    if (providerName === 'modal') {
      const orgModal = await loadOrgModalCredentials(
        ctx.prisma,
        (job as { orgId: string }).orgId,
      );
      provider = orgModal
        ? new ModalProvider({
            tokenId: orgModal.tokenId,
            tokenSecret: orgModal.tokenSecret,
            workspace: orgModal.workspace,
            environment: orgModal.environment,
            logger: log.child({ component: 'modal-provider', credentialScope: 'org' }),
            storage: ctx.storage,
          })
        : ctx.providers.get(providerName);
    } else {
      provider = ctx.providers.get(providerName);
    }
  } catch (err) {
    log.error({ err, providerName }, 'provider initialization failed');
    const message =
      err instanceof Error
        ? err.message
        : `provider initialization failed: ${providerName}`;
    await ctx.transitionJob(jobId, 'failed', {
      reason: message,
      error: { code: 'RUNTIME_ERROR', message, retryable: false },
    });
    await publish(ctx, jobId, errorEvent(false, message));
    return finish({
      outcome: 'failed',
      seedsCompleted: 0,
      retryable: false,
      errorCode: 'RUNTIME_ERROR',
      errorMessage: message,
    });
  }

  const rawRequest = (job as { params: unknown }).params;
  const rawRequestObject =
    rawRequest && typeof rawRequest === 'object' && !Array.isArray(rawRequest)
      ? (rawRequest as Record<string, unknown>)
      : {};
  const workflowRecord =
    rawRequestObject._papercraneWorkflow &&
    typeof rawRequestObject._papercraneWorkflow === 'object' &&
    !Array.isArray(rawRequestObject._papercraneWorkflow)
      ? (rawRequestObject._papercraneWorkflow as Record<string, unknown>)
      : undefined;
  const workflow = getPapercraneWorkflow(
    typeof workflowRecord?.id === 'string' ? workflowRecord.id : undefined,
  );
  const target = (job as {
    target?: { artifactKey?: string | null; pdbId?: string | null } | null;
  }).target;
  const request =
    rawRequest && typeof rawRequest === 'object'
      ? {
          ...(rawRequest as Record<string, unknown>),
          seeds: missingSeeds,
          ...(target?.pdbId ? { targetPdb: target.pdbId } : {}),
          // Saved RCSB targets can outlive their cached upload. Prefer the
          // canonical public structure whenever a PDB id exists; only stage
          // an owned artifact for upload-only targets.
          ...(target?.artifactKey && !target.pdbId
            ? {
                _papercrane: {
                  ...(((rawRequest as Record<string, unknown>)._papercrane as
                    | Record<string, unknown>
                    | undefined) ?? {}),
                  targetArtifactKey: target.artifactKey,
                },
              }
            : {}),
        }
      : rawRequest;

  const finalStageIndex = workflow ? workflow.stages.length - 1 : 0;
  const finalStage = workflow?.stages[finalStageIndex];
  let spawnInputs: ProviderSpawnInputs = {
    jobId,
    orgId: (job as { orgId: string }).orgId,
    toolId: finalStage?.toolId ?? (job as { tool: string }).tool,
    tier: input.tier ?? (job as { queueTier?: Tier }).queueTier ?? 'pro',
    request: workflow && finalStage
      ? workflowStageRequest(request, finalStage.params, false)
      : request,
    numSeeds: missingSeeds.length,
    ...(workflow
      ? { workflowStage: { index: finalStageIndex, total: workflow.stages.length } }
      : {}),
  };

  // A retry can arrive after every requested seed was already committed but
  // before the previous worker recorded success. Complete without spending
  // GPU time or billing those seeds twice.
  if (missingSeeds.length === 0) {
    await ctx.transitionJob(jobId, 'running');
    await publish(ctx, jobId, statusEvent('running'));
    await ctx.transitionJob(jobId, 'succeeded');
    await publish(ctx, jobId, statusEvent('succeeded'));
    await reconcileGpuSpend(ctx, {
      jobId,
      orgId: spawnInputs.orgId,
      numSeeds: requestedSeeds.length,
      seedsCompleted: existingSeeds.size,
      outcome: 'succeeded',
    });
    return finish({ outcome: 'succeeded', seedsCompleted: existingSeeds.size });
  }

  // Trusted workflow stages run sequentially. Intermediate outputs are
  // checkpointed on the job row and use stage-specific R2 keys, so a retry can
  // resume without rerunning expensive completed GPU work or overwriting the
  // artifact needed by the next stage.
  let runningTransitioned = false;
  if (workflow && finalStageIndex > 0) {
    const checkpoint = workflowCheckpoint(workflowRecord?.checkpoint, missingSeeds);
    let previousResults = checkpoint?.results;
    let nextStageIndex = checkpoint ? checkpoint.completedStage + 1 : 0;

    for (let stageIndex = nextStageIndex; stageIndex < finalStageIndex; stageIndex += 1) {
      const stage = workflow.stages[stageIndex]!;
      if (!runningTransitioned) {
        await ctx.transitionJob(jobId, 'running');
        await publish(ctx, jobId, statusEvent('running'));
        runningTransitioned = true;
      }
      log.info(
        { workflowId: workflow.id, stageIndex, toolId: stage.toolId },
        'workflow stage started',
      );

      const stageInputs: ProviderSpawnInputs = {
        ...spawnInputs,
        toolId: stage.toolId,
        request: workflowStageRequest(request, stage.params, stageIndex === 0),
        previousResults,
        workflowStage: { index: stageIndex, total: workflow.stages.length },
      };
      let stageSpawn: ProviderSpawnResult;
      try {
        stageSpawn = await provider.spawnJob(undefined, stageInputs);
      } catch (err) {
        return finish(
          await handleError(ctx, jobId, err, existingSeeds.size, attempt, 'running'),
        );
      }

      const seen = new Set<number>();
      const results: ProviderSeedResult[] = [];
      try {
        for await (const result of stageSpawn.seeds) {
          if (ctx.cancellation.isCancelled(jobId)) {
            await stageSpawn.cancel();
            await ctx.transitionJob(jobId, 'cancelling');
            await publish(ctx, jobId, statusEvent('cancelling'));
            await ctx.transitionJob(jobId, 'cancelled');
            await publish(ctx, jobId, statusEvent('cancelled'));
            await reconcileGpuSpend(ctx, {
              jobId,
              orgId: spawnInputs.orgId,
              numSeeds: requestedSeeds.length,
              seedsCompleted: existingSeeds.size,
              outcome: 'cancelled',
            });
            ctx.cancellation.clear(jobId);
            return finish({ outcome: 'cancelled', seedsCompleted: existingSeeds.size });
          }
          if (!missingSeeds.includes(result.seed) || seen.has(result.seed)) {
            const error: Error & { code?: string } = new Error(
              `workflow stage '${stage.toolId}' emitted an unexpected or duplicate seed ${result.seed}`,
            );
            error.code = 'INVALID_OUTPUT';
            throw error;
          }
          seen.add(result.seed);
          results.push(result);
        }
        const missing = missingSeeds.filter((seed) => !seen.has(seed));
        if (missing.length > 0) {
          const error: Error & { code?: string } = new Error(
            `workflow stage '${stage.toolId}' ended without seeds [${missing.join(',')}]`,
          );
          error.code = 'INFRA_ERROR';
          throw error;
        }
      } catch (err) {
        await stageSpawn.cancel().catch(() => undefined);
        return finish(
          await handleError(ctx, jobId, err, existingSeeds.size, attempt, 'running'),
        );
      }

      previousResults = results;
      nextStageIndex = stageIndex + 1;
      const nextWorkflowRecord = {
        ...workflowRecord,
        checkpoint: { completedStage: stageIndex, results },
      };
      await ctx.prisma.job.update({
        where: { id: jobId },
        data: {
          params: {
            ...rawRequestObject,
            _papercraneWorkflow: nextWorkflowRecord,
          } as unknown as Prisma.InputJsonValue,
        },
      });
      log.info(
        { workflowId: workflow.id, stageIndex, toolId: stage.toolId },
        'workflow stage checkpointed',
      );
    }

    spawnInputs = {
      ...spawnInputs,
      previousResults,
    };
  }

  let spawn: ProviderSpawnResult;
  try {
    spawn = await provider.spawnJob(undefined, spawnInputs);
  } catch (err) {
    return finish(
      await handleError(ctx, jobId, err, existingSeeds.size, attempt, 'preparing'),
    );
  }

  // ---- 4. Transition running ----
  if (!runningTransitioned) {
    await ctx.transitionJob(jobId, 'running');
    await publish(ctx, jobId, statusEvent('running'));
  }

  // ---- 5. Stream seeds ----
  let completed = existingSeeds.size;
  let cancelledMidRun = false;
  const expectedThisAttempt = new Set(missingSeeds);
  const emittedThisAttempt = new Set<number>();
  try {
    for await (const seedResult of spawn.seeds) {
      // Check cooperative cancel BEFORE persisting work so we don't write
      // anything after the user asked us to stop. Completed work already
      // persisted stays — that's the plan 01 §5 "flushes completed designs"
      // contract.
      if (ctx.cancellation.isCancelled(jobId)) {
        cancelledMidRun = true;
        break;
      }

      if (!expectedThisAttempt.has(seedResult.seed)) {
        const error: Error & { code?: string } = new Error(
          `provider returned unexpected seed ${seedResult.seed}`,
        );
        error.code = 'INVALID_OUTPUT';
        throw error;
      }
      if (emittedThisAttempt.has(seedResult.seed)) {
        const error: Error & { code?: string } = new Error(
          `provider returned duplicate seed ${seedResult.seed}`,
        );
        error.code = 'INVALID_OUTPUT';
        throw error;
      }
      emittedThisAttempt.add(seedResult.seed);

      const inserted = await persistSeed(
        ctx,
        spawnInputs.orgId,
        jobId,
        seedResult,
        attempt,
      );
      if (inserted) {
        existingSeeds.add(seedResult.seed);
        completed = existingSeeds.size;
      }

      if (inserted) {
        await publish(
          ctx,
          jobId,
          designEvent(seedResult.designId, seedResult.seed, seedResult.metrics),
        );
      }
      await publish(ctx, jobId, progressEvent(completed, requestedSeeds.length));

      // Check again AFTER publishing in case cancel arrived between yields.
      if (ctx.cancellation.isCancelled(jobId)) {
        cancelledMidRun = true;
        break;
      }
    }
  } catch (err) {
    // Best-effort provider cancel; don't let its failure mask the original.
    try {
      await spawn.cancel();
    } catch {
      /* ignored */
    }
    if (completed < requestedSeeds.length) {
      return finish(await handleError(ctx, jobId, err, completed, attempt, 'running'));
    }
    log.warn(
      { err, completed, requested: requestedSeeds.length },
      'provider errored after every requested seed was safely persisted; completing job',
    );
  }

  if (!cancelledMidRun && completed < requestedSeeds.length) {
    const error: Error & { code?: string } = new Error(
      `provider stream ended early: ${completed}/${requestedSeeds.length} seeds persisted`,
    );
    error.code = 'INFRA_ERROR';
    return finish(await handleError(ctx, jobId, error, completed, attempt, 'running'));
  }

  // ---- 6. Terminal transition ----
  if (cancelledMidRun) {
    await ctx.transitionJob(jobId, 'cancelling');
    await publish(ctx, jobId, statusEvent('cancelling'));
    try {
      await spawn.cancel();
    } catch (err) {
      log.warn({ err }, 'provider cancel failed during cooperative cancellation');
    }
    await ctx.transitionJob(jobId, 'cancelled');
    await publish(ctx, jobId, statusEvent('cancelled'));
    // Refund the unconsumed portion of the estimate back to the org cap.
    await reconcileGpuSpend(ctx, {
      jobId,
      orgId: spawnInputs.orgId,
      numSeeds: requestedSeeds.length,
      seedsCompleted: completed,
      outcome: 'cancelled',
    });
    ctx.cancellation.clear(jobId);
    return finish({ outcome: 'cancelled', seedsCompleted: completed });
  }

  await ctx.transitionJob(jobId, 'succeeded');
  await publish(ctx, jobId, statusEvent('succeeded'));
  await reconcileGpuSpend(ctx, {
    jobId,
    orgId: spawnInputs.orgId,
    numSeeds: requestedSeeds.length,
    seedsCompleted: completed,
    outcome: 'succeeded',
  });
  return finish({ outcome: 'succeeded', seedsCompleted: completed });
}

// ---------- helpers ----------

function workflowStageRequest(
  request: unknown,
  stageParams: Record<string, unknown>,
  includeSubmittedToolParams: boolean,
): unknown {
  if (!request || typeof request !== 'object' || Array.isArray(request)) {
    return { toolParams: { ...stageParams } };
  }
  const obj = request as Record<string, unknown>;
  const submitted =
    includeSubmittedToolParams &&
    obj.toolParams &&
    typeof obj.toolParams === 'object' &&
    !Array.isArray(obj.toolParams)
      ? (obj.toolParams as Record<string, unknown>)
      : {};
  return {
    ...obj,
    toolParams: { ...stageParams, ...submitted },
  };
}

function workflowCheckpoint(
  raw: unknown,
  requiredSeeds: number[],
): { completedStage: number; results: ProviderSeedResult[] } | undefined {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined;
  const checkpoint = raw as Record<string, unknown>;
  if (!Number.isInteger(checkpoint.completedStage) || !Array.isArray(checkpoint.results)) {
    return undefined;
  }
  const required = new Set(requiredSeeds);
  const results = checkpoint.results.filter(
    (value): value is ProviderSeedResult => {
      if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
      const result = value as Partial<ProviderSeedResult>;
      return (
        typeof result.seed === 'number' &&
        required.has(result.seed) &&
        typeof result.designId === 'string' &&
        typeof result.artifactKey === 'string' &&
        Boolean(result.metrics) &&
        typeof result.metrics === 'object'
      );
    },
  );
  if (results.length !== required.size) return undefined;
  return {
    completedStage: checkpoint.completedStage as number,
    results,
  };
}

function resolveRequestedSeeds(request: unknown, seedsRequested: number): number[] {
  if (request && typeof request === 'object') {
    const raw = (request as { seeds?: unknown }).seeds;
    if (Array.isArray(raw)) {
      const seeds = Array.from(
        new Set(raw.filter((value): value is number => Number.isInteger(value) && value >= 0)),
      );
      if (seeds.length === seedsRequested) return seeds;
    }
  }
  return Array.from({ length: Math.max(0, seedsRequested) }, (_value, index) => index + 1);
}

async function registerAttempt(
  ctx: WorkerContext,
  jobId: string,
  attempt: number,
  completedSeeds: number,
): Promise<boolean> {
  // Cast locally so workers built before the accompanying Prisma generate can
  // still typecheck during a rolling deploy.
  const jobModel = ctx.prisma.job as unknown as {
    update: (args: unknown) => Promise<unknown>;
    updateMany?: (args: unknown) => Promise<{ count: number }>;
  };
  if (jobModel.updateMany) {
    const result = await jobModel.updateMany({
      where: { id: jobId, status: 'preparing', attempt: { lte: attempt } },
      data: { attempt, heartbeatAt: new Date(), seedsConsumed: completedSeeds },
    });
    return result.count === 1;
  }
  await jobModel.update({
    where: { id: jobId },
    data: { attempt, heartbeatAt: new Date(), seedsConsumed: completedSeeds },
  });
  return true;
}

function startHeartbeat(ctx: WorkerContext, jobId: string, attempt: number): () => void {
  const jobModel = ctx.prisma.job as unknown as {
    updateMany?: (args: unknown) => Promise<{ count: number }>;
  };
  if (!jobModel.updateMany) return () => undefined;

  const timer = setInterval(() => {
    void jobModel
      .updateMany!({
        where: { id: jobId, attempt, status: { in: ['preparing', 'running'] } },
        data: { heartbeatAt: new Date() },
      })
      .catch((err) => {
        ctx.logger.warn({ err, jobId, attempt }, 'job heartbeat update failed');
      });
  }, 30_000);
  timer.unref?.();
  return () => clearInterval(timer);
}

async function publish(ctx: WorkerContext, jobId: string, event: JobEvent): Promise<void> {
  await persistJobEvent(ctx.prisma, ctx.logger, jobId, event);
  await ctx.eventPublisher.publish(jobId, event);
}

async function persistSeed(
  ctx: WorkerContext,
  orgId: string,
  jobId: string,
  seed: ProviderSeedResult,
  attempt: number,
): Promise<boolean> {
  // Validate + normalise metrics at the persist boundary. Out-of-casing keys
  // get canonicalised, physically-impossible values are dropped (never hard-
  // fail — we don't want to lose a real result over one bad number).
  const rawMetrics: Record<string, unknown> = {
    ...(seed.metrics ?? {}),
    ...(seed.sequence ? { sequence: seed.sequence, length: seed.sequence.length } : {}),
  };
  const { metrics: normalized, valid, warnings } = validateMetrics(rawMetrics);
  if (!valid) {
    ctx.logger.warn(
      { jobId, seed: seed.seed, warnings },
      'seed metrics failed validation; dropped out-of-range/invalid values',
    );
  }
  // Carry the validity marker forward so the UI/exports can flag suspect rows.
  const metricsToStore = valid ? normalized : { ...normalized, validation: 'warn' };

  // Provenance: real for the worker path, unless the incoming metrics self-
  // identify as a Modal-stub fabrication (provenance:'stub').
  const provenance = rawMetrics.provenance === 'stub' ? 'stub' : 'real';

  // Single tx: persist the design and debit the org allocation ledger together.
  return ctx.prisma.$transaction(async (tx: unknown) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const txAny = tx as any;
    const lease = await txAny.job.updateMany?.({
      where: { id: jobId, status: 'running', attempt },
      data: { heartbeatAt: new Date() },
    });
    if (lease && lease.count === 0) {
      const stale: Error & { code?: string } = new Error(
        `worker attempt ${attempt} no longer owns job ${jobId}`,
      );
      stale.code = 'WORKER_STALLED';
      throw stale;
    }

    const data = {
      jobId,
      orgId,
      seed: seed.seed,
      metrics: metricsToStore,
      artifactKey: seed.artifactKey,
      provenance,
    };
    let inserted = 0;
    if (txAny.design?.createMany) {
      const result = await txAny.design.createMany({ data: [data], skipDuplicates: true });
      inserted = Number(result?.count ?? 0);
    } else if (txAny.design?.create) {
      await txAny.design.create({
        data,
      });
      inserted = 1;
    }
    if (inserted === 0) return false;
    await txAny.job.update({
      where: { id: jobId },
      data: { seedsConsumed: { increment: 1 } },
    });
    await txAny.organization?.update?.({
      where: { id: orgId },
      data: { seedsUsed: { increment: 1 } },
    });
    await txAny.usageSeed?.create?.({
      data: {
        orgId,
        jobId,
        seeds: 1,
        reason: 'job_seed_completed',
      },
    });
    return true;
  });
}

function handleError(
  ctx: WorkerContext,
  jobId: string,
  err: unknown,
  completed: number,
  attempt: number,
  stage: 'preparing' | 'running',
): Promise<ProcessJobResult> {
  const code = extractCode(err);
  const message = err instanceof Error ? err.message : String(err);
  const retryable = INFRA_SET.has(code);

  return (async () => {
    // A failed `(status, attempt)` guard means another worker/sweeper already
    // fenced this process and owns recovery. Do not overwrite its newer state
    // or enqueue a second retry from the stale process.
    if (code === 'WORKER_STALLED') {
      ctx.logger.warn({ jobId, attempt, completed }, 'stale worker attempt stopped');
      return {
        outcome: 'failed',
        seedsCompleted: completed,
        retryable: false,
        errorCode: code,
        errorMessage: message,
      };
    }
    if (stage === 'running' && completed > 0) {
      await ctx.transitionJob(jobId, 'partial', {
        reason: `${completed} seeds persisted before failure`,
      });
      await publish(ctx, jobId, statusEvent('partial'));
    }
    await ctx.transitionJob(jobId, 'failed', {
      reason: message,
      error: { code, message, retryable, attempt, completedSeeds: completed },
    });
    await publish(ctx, jobId, errorEvent(retryable, message));
    ctx.logger.error({ jobId, err, code, retryable, completed }, 'job failed');
    // Refund any unconsumed portion of the estimate. We look up the job to
    // recover (orgId, seedsRequested); if either is missing we silently skip
    // — better than crashing the worker because of a billing bookkeeping
    // edge case.
    try {
      const job = await ctx.prisma.job.findUnique({
        where: { id: jobId },
        select: { orgId: true, seedsRequested: true },
      });
      if (job) {
        await reconcileGpuSpend(ctx, {
          jobId,
          orgId: (job as { orgId: string }).orgId,
          numSeeds: Number((job as { seedsRequested: number }).seedsRequested ?? 0),
          seedsCompleted: completed,
          outcome: 'failed',
        });
      }
    } catch (reconcileErr) {
      ctx.logger.warn({ reconcileErr, jobId }, 'gpu spend reconciliation skipped after failure');
    }
    return {
      outcome: 'failed',
      seedsCompleted: completed,
      retryable,
      errorCode: code,
      errorMessage: message,
    };
  })();
}

/**
 * Reconcile the org's GPU spend after a job terminates.
 *
 * Three signals can update the ledger:
 *
 *   1. Modal-reported runtime (when available) → set actualUsd / secondsActual
 *      on the GpuSpend row and adjust the org running total by
 *      `actualUsd - estimatedUsd`.
 *
 *   2. Job failed / cancelled with N < numSeeds completed → refund the
 *      unconsumed portion `(numSeeds - seedsCompleted) / numSeeds × estimated`
 *      back to the org running total. The ledger row's `actualUsd` becomes
 *      the consumed portion so the dashboard reflects what was actually spent.
 *
 *   3. Successful job with no actual-cost signal → leave the estimate in place.
 *
 * All updates happen in a single transaction. Bookkeeping errors are caught
 * by the caller — never let billing math crash the worker.
 */
interface ReconcileOpts {
  jobId: string;
  orgId: string;
  numSeeds: number;
  seedsCompleted: number;
  outcome: 'succeeded' | 'cancelled' | 'failed';
  /** Optional Modal-reported runtime in seconds. Populated by the HTTP-client path. */
  modalSeconds?: number;
}

async function reconcileGpuSpend(
  ctx: WorkerContext,
  opts: ReconcileOpts,
): Promise<void> {
  const { jobId, orgId, numSeeds, seedsCompleted, outcome, modalSeconds } = opts;
  try {
    await ctx.prisma.$transaction(async (tx: unknown) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const txAny = tx as any;
      const ledgerRow = (await txAny.gpuSpend?.findFirst?.({
        where: { jobId },
        orderBy: { createdAt: 'desc' },
      })) as
        | {
            id: bigint | string | number;
            estimatedUsd: Prisma.Decimal | string | number;
            gpuType: string;
            actualUsd?: Prisma.Decimal | string | number | null;
          }
        | null;
      if (!ledgerRow) return; // No row to reconcile — submit didn't write one (legacy).

      const estimated = new Prisma.Decimal(ledgerRow.estimatedUsd);

      // Compute actual cost. Priority: Modal seconds > pro-rated estimate by
      // seedsCompleted > full estimate (clean success).
      let actual: Prisma.Decimal;
      let secondsActual: number | null = null;
      if (typeof modalSeconds === 'number' && modalSeconds > 0) {
        const fromModal = actualCostFromModalSeconds(ledgerRow.gpuType, modalSeconds);
        actual = fromModal ?? estimated;
        secondsActual = Math.round(modalSeconds);
      } else if (outcome !== 'succeeded' && numSeeds > 0) {
        // Pro-rate by completion fraction. seedsCompleted = 0 → 100% refund.
        const fraction = Math.max(0, Math.min(1, seedsCompleted / numSeeds));
        actual = estimated.mul(fraction.toFixed(6));
      } else {
        actual = estimated;
      }

      // The org total already reflects either the original reservation or a
      // previous reconciliation attempt. Comparing against the ledger's
      // current charge makes retries idempotent and lets a later successful
      // retry restore a charge that an earlier failed attempt refunded.
      const currentCharge =
        ledgerRow.actualUsd === null || ledgerRow.actualUsd === undefined
          ? estimated
          : new Prisma.Decimal(ledgerRow.actualUsd);
      const delta = actual.sub(currentCharge); // negative if we're refunding

      await txAny.gpuSpend?.update?.({
        where: { id: ledgerRow.id },
        data: {
          actualUsd: actual,
          ...(secondsActual !== null ? { secondsActual } : {}),
        },
      });
      if (!delta.eq(0)) {
        await txAny.$executeRawUnsafe?.(
          'UPDATE organizations SET gpu_spend_usd = GREATEST(0, gpu_spend_usd + $1::numeric) WHERE id = $2::uuid',
          delta.toString(),
          orgId,
        );
      }
    });
  } catch (err) {
    ctx.logger.warn({ err, jobId }, 'gpu spend reconciliation failed (non-fatal)');
  }
}

function extractCode(err: unknown): string {
  if (err && typeof err === 'object') {
    const e = err as { code?: unknown };
    if (typeof e.code === 'string') {
      if (INFRA_SET.has(e.code) || USER_SET.has(e.code)) return e.code;
      return e.code;
    }
  }
  return 'UNKNOWN';
}
