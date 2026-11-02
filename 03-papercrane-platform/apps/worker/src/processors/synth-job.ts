/**
 * Synthetic job processor — DEV MODE ONLY.
 *
 * Wave 11 brief: when `NODE_ENV !== 'production'` AND the in-memory queue is
 * active (Redis fallback path in `dev-queue.ts`), we cannot dispatch real GPU
 * work via Modal. This processor stands in: it walks the requested tool chain,
 * sleeps a few seconds per stage to mimic compute, then writes a handful of
 * realistic Design rows and marks the Job 'succeeded'. It is what powers the
 * end-to-end "submit → see designs" flow during local development without
 * requiring Modal/Vast/RunPod credentials.
 *
 * Hard guarantees:
 *   - Refuses to run when `NODE_ENV === 'production'` (throws). The dev-queue
 *     handler is also gated on the same check, but defense in depth.
 *   - Never imports the Modal client. This module exists to bypass GPU code.
 *   - Writes only via the same Prisma client the production processor uses,
 *     so RLS + retention sweeps still apply to synthetic rows.
 *
 * Realistic-ish data (within published binder ranges):
 *   - 80-aa AA sequence drawn from the 20 canonical residues
 *   - ipTM ∈ [0.45, 0.85], pAE ∈ [5, 25], pDockQ ∈ [0.20, 0.70], pLDDT ∈ [60,90]
 *   - Tiny placeholder cif blob keyed under `synth/<jobId>/<seed>.cif` — the
 *     UI viewer falls back to PDB 1CRN when the artifact isn't in R2 yet.
 */

import type { PrismaClient } from '@papercrane/db';
import type { Logger } from '@papercrane/observability';

export interface SynthJobInput {
  jobId: string;
  /**
   * Optional list of tool ids run in sequence. If omitted we read the job's
   * single `tool` column from the row. Either way, each entry costs ~5s of
   * fake compute and emits a status update.
   */
  toolChain?: string[];
}

export interface SynthJobDeps {
  prisma: PrismaClient;
  logger: Logger;
  /** Override the per-stage sleep in tests so they don't take 15+ seconds. */
  sleepMs?: number;
  /** Deterministic seed for tests — defaults to Math.random. */
  rng?: () => number;
}

export interface SynthJobResult {
  outcome: 'succeeded' | 'failed';
  designsCreated: number;
  toolStages: number;
}

const AA_ALPHABET = 'ACDEFGHIKLMNPQRSTVWY';

/**
 * Run the synthetic processor against an existing Job row.
 *
 * The dev-queue handler in `server.ts` calls this in the dev fallback branch.
 * Production code paths (BullMQ workers in `index.ts → bootstrapWorkers`) keep
 * using the real `processJob` against the Modal provider.
 */
export async function runSynthJob(
  deps: SynthJobDeps,
  input: SynthJobInput,
): Promise<SynthJobResult> {
  if (process.env.NODE_ENV === 'production') {
    throw new Error(
      'runSynthJob refused: NODE_ENV=production. Synthetic jobs are dev-only.',
    );
  }

  const { prisma, logger } = deps;
  const sleepMs = deps.sleepMs ?? 5_000;
  const rng = deps.rng ?? Math.random;
  const log = logger.child({ jobId: input.jobId, processor: 'synth' });

  // ---- Load job row ----
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const jobRow: any = await (prisma as any).job.findUnique({
    where: { id: input.jobId },
  });
  if (!jobRow) {
    log.error('synth processor: job row missing');
    return { outcome: 'failed', designsCreated: 0, toolStages: 0 };
  }

  const orgId: string = jobRow.orgId;
  const seedsRequested: number = Number(jobRow.seedsRequested ?? 0);
  // The router stamps the picked tool into `tool`. Multi-tool chains are
  // surfaced through a `toolChain` array on `params` (added by the picker UI
  // in a sibling Wave-11 agent) — fall back to the single `tool` if absent.
  const params = (jobRow.params ?? {}) as Record<string, unknown>;
  const chainFromParams = Array.isArray(params.toolChain)
    ? (params.toolChain as string[])
    : null;
  const toolChain: string[] =
    input.toolChain && input.toolChain.length > 0
      ? input.toolChain
      : chainFromParams && chainFromParams.length > 0
        ? chainFromParams
        : [String(jobRow.tool ?? 'unknown')];

  log.info({ toolChain, seedsRequested }, 'synth processor: starting');

  // ---- preparing → running ----
  await safeUpdateJob(prisma, input.jobId, {
    status: 'preparing',
    startedAt: new Date(),
  });

  // Walk the tool chain. Each stage gets a status bump on `params.synthStage`
  // so the UI poll picks up progress even without LISTEN/NOTIFY wiring.
  for (let i = 0; i < toolChain.length; i++) {
    await sleep(sleepMs);
    await safeUpdateJob(prisma, input.jobId, {
      status: 'running',
      params: {
        ...params,
        toolChain,
        synthStage: { index: i, name: toolChain[i], total: toolChain.length },
      },
    });
    log.info({ stage: toolChain[i], i }, 'synth processor: stage complete');
  }

  // ---- Generate 3-10 designs (capped at seedsRequested if smaller) ----
  const target = clamp(3 + Math.floor(rng() * 8), 1, Math.max(1, seedsRequested || 10));
  let created = 0;
  for (let s = 0; s < target; s++) {
    const seq = randomSequence(80, rng);
    const metrics = synthMetrics(rng);
    const cifKey = `synth/${input.jobId}/${s}.cif`;
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      await (prisma as any).$transaction(async (tx: any) => {
        await tx.design.create({
          data: {
            jobId: input.jobId,
            orgId,
            seed: s,
            metrics: { ...metrics, length: 80, sequence: seq, cifFallbackPdb: '1CRN' },
            artifactKey: cifKey,
            rank: s + 1,
            // First-class marker: these rows are fabricated dev fixtures, never
            // real model output. Queryable + bannered in the UI.
            provenance: 'synthetic',
          },
        });
        await tx.job.update({
          where: { id: input.jobId },
          data: { seedsConsumed: { increment: 1 } },
        });
      });
      created += 1;
    } catch (err) {
      log.warn({ err, seed: s }, 'synth processor: failed to insert design row');
    }
  }

  await safeUpdateJob(prisma, input.jobId, {
    status: 'succeeded',
    completedAt: new Date(),
  });

  log.info({ designsCreated: created, toolStages: toolChain.length }, 'synth processor: done');
  return { outcome: 'succeeded', designsCreated: created, toolStages: toolChain.length };
}

// ---------- helpers ----------

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    const t = setTimeout(resolve, ms);
    t.unref?.();
  });
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}

function randomSequence(length: number, rng: () => number): string {
  let out = '';
  for (let i = 0; i < length; i++) {
    out += AA_ALPHABET[Math.floor(rng() * AA_ALPHABET.length)];
  }
  return out;
}

function synthMetrics(rng: () => number): Record<string, number> {
  const round = (x: number) => Math.round(x * 1000) / 1000;
  return {
    iptm: round(0.45 + rng() * 0.4),
    ipsae: round(0.4 + rng() * 0.45),
    pae: round(5 + rng() * 20),
    pdockq: round(0.2 + rng() * 0.5),
    plddt: round(60 + rng() * 30),
    dockq: round(0.2 + rng() * 0.5),
  };
}

async function safeUpdateJob(
  prisma: PrismaClient,
  jobId: string,
  data: Record<string, unknown>,
): Promise<void> {
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (prisma as any).job.update({ where: { id: jobId }, data });
  } catch {
    /* swallow — synth processor must never crash the worker */
  }
}
