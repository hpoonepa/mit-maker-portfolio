/**
 * jobProcessor tests — happy path, cancellation, infra retry, user error.
 *
 * The processor is exercised in-memory: we stub Redis, Prisma, the provider
 * registry, and the event publisher. This keeps tests deterministic and under
 * 2s total runtime.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { WorkerContext } from '../src/context';
import { processJob } from '../src/jobProcessor';
import type { Provider, ProviderSpawnResult } from '../src/providers/types';
import { CancellationManager } from '../src/cancellation';

// ---------- Test fixtures ----------

type JobRow = {
  id: string;
  orgId: string;
  tool: string;
  toolVersion: string;
  seedsRequested: number;
  seedsConsumed: number;
  status: string;
  params: Record<string, unknown>;
  attempt: number;
  tier: 'free' | 'pro' | 'frontier';
  error?: { code: string; message: string; retryable?: boolean } | null;
  startedAt?: Date | null;
  completedAt?: Date | null;
  designs?: Array<{ seed: number }>;
  target?: { artifactKey?: string | null; pdbId?: string | null } | null;
};

function mkJob(overrides: Partial<JobRow> = {}): JobRow {
  return {
    id: 'job-1',
    orgId: 'org-1',
    tool: 'bindcraft',
    toolVersion: '1.0.0',
    seedsRequested: 3,
    seedsConsumed: 0,
    status: 'queued',
    params: { targetPdb: 'r2://t.pdb', seeds: [1, 2, 3], numDesigns: 3 },
    attempt: 1,
    tier: 'pro',
    ...overrides,
  };
}

function mkProvider(
  seeds: Array<{ seed: number; metrics: Record<string, number> }>,
  options: { delayMs?: number; throwAfter?: number; errorCode?: string } = {},
): Provider {
  return {
    name: 'mock',
    async spawnJob(_manifest, _inputs): Promise<ProviderSpawnResult> {
      const iter = (async function* () {
        let i = 0;
        for (const s of seeds) {
          if (options.throwAfter !== undefined && i >= options.throwAfter) {
            const e: Error & { code?: string } = new Error('provider blew up');
            e.code = options.errorCode ?? 'GPU_PREEMPT';
            throw e;
          }
          if (options.delayMs) await new Promise((r) => setTimeout(r, options.delayMs));
          i += 1;
          yield {
            designId: `d-${s.seed}`,
            seed: s.seed,
            metrics: s.metrics,
            artifactKey: `orgs/org-1/jobs/job-1/designs/${s.seed}.cif`,
          };
        }
      })();
      return {
        spawnId: 'spawn-abc',
        estimatedSeconds: 60,
        seeds: iter,
        async cancel() {
          /* no-op */
        },
      };
    },
    async cancelJob() {
      /* no-op */
    },
    async getCost() {
      return { usd: 0 };
    },
  };
}

function mkContext(overrides: Partial<WorkerContext> = {}): WorkerContext {
  const transitions: Array<{ jobId: string; next: string }> = [];
  const events: Array<{ jobId: string; event: unknown }> = [];
  const jobs = new Map<string, JobRow>();

  const ctx: WorkerContext = {
    prisma: {
      job: {
        findUnique: vi.fn(async ({ where }: { where: { id: string } }) => {
          return jobs.get(where.id) ?? null;
        }),
        update: vi.fn(
          async ({ where, data }: { where: { id: string }; data: Record<string, unknown> }) => {
            const current = jobs.get(where.id);
            if (!current) throw new Error('job not found');
            // Handle Prisma `{ increment: n }` sentinel for numeric counters.
            const resolved: Record<string, unknown> = {};
            for (const [k, v] of Object.entries(data)) {
              if (v && typeof v === 'object' && 'increment' in (v as object)) {
                const prev = (current as unknown as Record<string, number>)[k] ?? 0;
                resolved[k] = prev + (v as { increment: number }).increment;
              } else {
                resolved[k] = v;
              }
            }
            const next = { ...current, ...resolved } as JobRow;
            jobs.set(where.id, next);
            return next;
          },
        ),
      },
      design: {
        create: vi.fn(async ({ data }: { data: unknown }) => data),
      },
      organization: {
        update: vi.fn(async ({ data }: { data: unknown }) => data),
      },
      usageSeed: {
        create: vi.fn(async ({ data }: { data: unknown }) => data),
      },
      jobLog: {
        create: vi.fn(async ({ data }: { data: unknown }) => data),
      },
      gpuSpend: {
        findFirst: vi.fn().mockResolvedValue(null),
        update: vi.fn(async ({ data }: { data: unknown }) => data),
      },
      $queryRaw: vi.fn().mockResolvedValue([]),
      $executeRawUnsafe: vi.fn().mockResolvedValue(1),
      $transaction: vi.fn(async (fn: (tx: unknown) => Promise<unknown>) => fn(ctx.prisma)),
    } as unknown as WorkerContext['prisma'],

    redis: {
      publish: vi.fn(async () => 1),
    } as unknown as WorkerContext['redis'],

    logger: {
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
      child: vi.fn().mockReturnThis(),
    } as unknown as WorkerContext['logger'],

    eventPublisher: {
      publish: vi.fn(async (jobId: string, event: unknown) => {
        events.push({ jobId, event });
      }),
    },

    providers: {
      get: vi.fn((name: string) => mkProvider([])),
      register: vi.fn(),
      list: vi.fn(() => ['modal']),
    },

    cancellation: new CancellationManager(),

    transitionJob: vi.fn(async (
      jobId: string,
      next: string,
      opts?: { error?: JobRow['error'] },
    ) => {
      transitions.push({ jobId, next });
      const current = jobs.get(jobId);
      if (current) jobs.set(jobId, { ...current, status: next, error: opts?.error ?? current.error });
    }),

    ...overrides,
  };

  // Expose test-hooks on the context so assertions can see what happened.
  (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs = jobs;
  (ctx as unknown as { __transitions: typeof transitions }).__transitions = transitions;
  (ctx as unknown as { __events: typeof events }).__events = events;

  return ctx;
}

// ---------- Tests ----------

describe('processJob — happy path', () => {
  it('runs queued → preparing → running → succeeded and emits a design event per seed', async () => {
    const job = mkJob();
    const ctx = mkContext();
    (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.set(job.id, job);

    const provider = mkProvider([
      { seed: 1, metrics: { ipsae: 0.8 } },
      { seed: 2, metrics: { ipsae: 0.7 } },
      { seed: 3, metrics: { ipsae: 0.6 } },
    ]);
    (ctx.providers.get as ReturnType<typeof vi.fn>).mockReturnValue(provider);

    await processJob(ctx, { jobId: job.id });

    const transitions = (ctx as unknown as { __transitions: Array<{ next: string }> }).__transitions;
    const statuses = transitions.map((t) => t.next);
    expect(statuses).toEqual(['preparing', 'running', 'succeeded']);

    const events = (ctx as unknown as { __events: Array<{ event: { type: string } }> }).__events;
    const designEvents = events.filter((e) => e.event.type === 'design');
    expect(designEvents).toHaveLength(3);

    const finalJob = (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.get(job.id)!;
    expect(finalJob.seedsConsumed).toBe(3);
    expect(finalJob.status).toBe('succeeded');
    const prisma = ctx.prisma as unknown as {
      organization: { update: ReturnType<typeof vi.fn> };
      usageSeed: { create: ReturnType<typeof vi.fn> };
    };
    expect(prisma.organization.update).toHaveBeenCalledTimes(3);
    expect(prisma.usageSeed.create).toHaveBeenCalledTimes(3);
    expect((ctx.prisma as never as { jobLog: { create: ReturnType<typeof vi.fn> } }).jobLog.create)
      .toHaveBeenCalledTimes(9);
  });

  it('passes the authoritative BullMQ queue tier to the provider', async () => {
    const job = mkJob({ seedsRequested: 1, tier: 'pro' });
    const ctx = mkContext();
    (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.set(job.id, job);
    const provider = mkProvider([{ seed: 1, metrics: {} }]);
    const spawnSpy = vi.spyOn(provider, 'spawnJob');
    (ctx.providers.get as ReturnType<typeof vi.fn>).mockReturnValue(provider);

    await processJob(ctx, { jobId: job.id, tier: 'frontier' });

    expect(spawnSpy).toHaveBeenCalledWith(
      undefined,
      expect.objectContaining({ tier: 'frontier' }),
    );
  });

  it('runs a trusted workflow sequentially and persists only final-stage designs', async () => {
    const job = mkJob({
      tool: 'rfdiffusion+proteinmpnn+boltz2',
      params: {
        targetPdb: '1UBQ',
        seeds: [1, 2, 3],
        numDesigns: 3,
        _papercraneWorkflow: {
          id: 'binder-standard',
          version: 1,
        },
      },
    });
    const ctx = mkContext();
    (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.set(job.id, job);
    const provider = mkProvider([
      { seed: 1, metrics: { ipsae: 0.8 } },
      { seed: 2, metrics: { ipsae: 0.7 } },
      { seed: 3, metrics: { ipsae: 0.6 } },
    ]);
    const spawnSpy = vi.spyOn(provider, 'spawnJob');
    (ctx.providers.get as ReturnType<typeof vi.fn>).mockReturnValue(provider);

    const result = await processJob(ctx, { jobId: job.id });

    expect(result.outcome).toBe('succeeded');
    expect(spawnSpy.mock.calls.map((call) => call[1].toolId)).toEqual([
      'rfdiffusion',
      'proteinmpnn',
      'boltz2',
    ]);
    expect(spawnSpy.mock.calls[1]?.[1].previousResults).toHaveLength(3);
    expect(spawnSpy.mock.calls[2]?.[1].previousResults).toHaveLength(3);
    expect((ctx.prisma.design.create as ReturnType<typeof vi.fn>)).toHaveBeenCalledTimes(3);
    expect(
      (ctx.prisma.job.update as ReturnType<typeof vi.fn>).mock.calls.filter(
        ([arg]) => Boolean((arg as { data?: { params?: unknown } }).data?.params),
      ),
    ).toHaveLength(2);
  });

  it('prefers a canonical PDB id over a stale cached target artifact', async () => {
    const job = mkJob({
      seedsRequested: 1,
      params: { targetPdb: '5MV5', seeds: [1], numDesigns: 1 },
      target: {
        pdbId: '5MV5',
        artifactKey: 'orgs/org-1/uploads/missing/5MV5.pdb',
      },
    });
    const ctx = mkContext();
    (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.set(job.id, job);
    const provider = mkProvider([{ seed: 1, metrics: {} }]);
    const spawnSpy = vi.spyOn(provider, 'spawnJob');
    (ctx.providers.get as ReturnType<typeof vi.fn>).mockReturnValue(provider);

    await processJob(ctx, { jobId: job.id });

    expect(spawnSpy).toHaveBeenCalledWith(
      undefined,
      expect.objectContaining({
        request: expect.objectContaining({
          targetPdb: '5MV5',
          seeds: [1],
        }),
      }),
    );
    const request = spawnSpy.mock.calls[0]?.[1].request as Record<string, unknown>;
    expect(request._papercrane).toBeUndefined();
  });
});

describe('processJob — cancellation', () => {
  it('flushes completed seeds and transitions to cancelled when flag is set mid-run', async () => {
    const job = mkJob({ seedsRequested: 5 });
    const ctx = mkContext();
    (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.set(job.id, job);

    const provider = mkProvider(
      [
        { seed: 1, metrics: { ipsae: 0.8 } },
        { seed: 2, metrics: { ipsae: 0.7 } },
        { seed: 3, metrics: { ipsae: 0.6 } },
        { seed: 4, metrics: { ipsae: 0.5 } },
        { seed: 5, metrics: { ipsae: 0.4 } },
      ],
      { delayMs: 5 },
    );
    (ctx.providers.get as ReturnType<typeof vi.fn>).mockReturnValue(provider);

    // Request cancellation after 2 seeds have been consumed.
    const spy = ctx.eventPublisher.publish as ReturnType<typeof vi.fn>;
    let designCount = 0;
    spy.mockImplementation(async (_jobId: string, event: { type: string }) => {
      if (event.type === 'design') {
        designCount += 1;
        if (designCount === 2) ctx.cancellation.cancel(job.id);
      }
    });

    await processJob(ctx, { jobId: job.id });

    const transitions = (ctx as unknown as { __transitions: Array<{ next: string }> }).__transitions;
    const statuses = transitions.map((t) => t.next);
    expect(statuses).toContain('cancelling');
    expect(statuses[statuses.length - 1]).toBe('cancelled');

    const finalJob = (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.get(job.id)!;
    // We completed ≥ 2 seeds before cancel observed, < requested.
    expect(finalJob.seedsConsumed).toBeGreaterThanOrEqual(2);
    expect(finalJob.seedsConsumed).toBeLessThan(job.seedsRequested);
  });
});

describe('processJob — infra retry', () => {
  it('fails, marks retryable, and emits an error event with retryable=true', async () => {
    const job = mkJob();
    const ctx = mkContext();
    (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.set(job.id, job);

    const provider = mkProvider(
      [
        { seed: 1, metrics: { ipsae: 0.8 } },
        { seed: 2, metrics: { ipsae: 0.7 } },
        { seed: 3, metrics: { ipsae: 0.6 } },
      ],
      { throwAfter: 1, errorCode: 'GPU_PREEMPT' },
    );
    (ctx.providers.get as ReturnType<typeof vi.fn>).mockReturnValue(provider);

    const result = await processJob(ctx, { jobId: job.id });
    expect(result.outcome).toBe('failed');
    expect(result.retryable).toBe(true);

    const events = (ctx as unknown as { __events: Array<{ event: { type: string; retryable?: boolean } }> }).__events;
    const errorEvt = events.find((e) => e.event.type === 'error');
    expect(errorEvt?.event.retryable).toBe(true);

    const transitions = (ctx as unknown as { __transitions: Array<{ next: string }> }).__transitions;
    expect(transitions.map((t) => t.next)).toContain('failed');
    expect(transitions.map((t) => t.next)).toContain('partial');
    const finalJob = (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.get(job.id)!;
    expect(finalJob.error).toEqual({
      code: 'GPU_PREEMPT',
      message: 'provider blew up',
      retryable: true,
      attempt: 1,
      completedSeeds: 1,
    });
  });
});

describe('processJob — resumability and idempotency', () => {
  it('requests only missing seeds and keeps total progress across attempts', async () => {
    const job = mkJob({
      status: 'queued',
      seedsConsumed: 1,
      designs: [{ seed: 1 }],
    });
    const ctx = mkContext();
    (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.set(job.id, job);
    const provider = mkProvider([
      { seed: 2, metrics: { ipsae: 0.7 } },
      { seed: 3, metrics: { ipsae: 0.6 } },
    ]);
    const spawnSpy = vi.spyOn(provider, 'spawnJob');
    (ctx.providers.get as ReturnType<typeof vi.fn>).mockReturnValue(provider);

    const result = await processJob(ctx, { jobId: job.id, attempt: 2 });

    expect(result).toMatchObject({ outcome: 'succeeded', seedsCompleted: 3 });
    expect(spawnSpy).toHaveBeenCalledWith(
      undefined,
      expect.objectContaining({
        numSeeds: 2,
        request: expect.objectContaining({ seeds: [2, 3] }),
      }),
    );
    expect(
      (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.get(job.id)?.seedsConsumed,
    ).toBe(3);
  });

  it('does not spawn a provider when all requested seeds are already persisted', async () => {
    const job = mkJob({
      status: 'queued',
      seedsConsumed: 3,
      designs: [{ seed: 1 }, { seed: 2 }, { seed: 3 }],
    });
    const ctx = mkContext();
    (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.set(job.id, job);
    const provider = mkProvider([]);
    const spawnSpy = vi.spyOn(provider, 'spawnJob');
    (ctx.providers.get as ReturnType<typeof vi.fn>).mockReturnValue(provider);

    const result = await processJob(ctx, { jobId: job.id, attempt: 2 });

    expect(result).toMatchObject({ outcome: 'succeeded', seedsCompleted: 3 });
    expect(spawnSpy).not.toHaveBeenCalled();
    expect(
      (ctx.prisma as unknown as { design: { create: ReturnType<typeof vi.fn> } }).design.create,
    ).not.toHaveBeenCalled();
  });

  it('does not persist or bill a duplicate emitted after the job is complete', async () => {
    const job = mkJob({
      seedsRequested: 1,
      params: { seeds: [1], numDesigns: 1 },
    });
    const ctx = mkContext();
    (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.set(job.id, job);
    const seen = new Set<number>();
    const createMany = vi.fn(async ({ data }: { data: Array<{ seed: number }> }) => {
      const seed = data[0]!.seed;
      if (seen.has(seed)) return { count: 0 };
      seen.add(seed);
      return { count: 1 };
    });
    (ctx.prisma as unknown as { design: { createMany: typeof createMany } }).design.createMany =
      createMany;
    (ctx.providers.get as ReturnType<typeof vi.fn>).mockReturnValue(
      mkProvider([
        { seed: 1, metrics: { ipsae: 0.8 } },
        { seed: 1, metrics: { ipsae: 0.8 } },
      ]),
    );

    const result = await processJob(ctx, { jobId: job.id });

    expect(result).toMatchObject({ outcome: 'succeeded', seedsCompleted: 1 });
    expect(createMany).toHaveBeenCalledTimes(1);
    expect(
      (ctx.prisma as unknown as { usageSeed: { create: ReturnType<typeof vi.fn> } }).usageSeed
        .create,
    ).toHaveBeenCalledTimes(1);
  });
});

describe('processJob — design provenance + metric validation', () => {
  it('stamps provenance=real and normalises/validates metrics on the persisted design', async () => {
    const job = mkJob({ seedsRequested: 1 });
    const ctx = mkContext();
    (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.set(job.id, job);

    // Provider emits lowercase aliases + one out-of-range value.
    const provider = mkProvider([
      { seed: 1, metrics: { iptm: 0.8, ipsae: 0.7, plddt: 140 } },
    ]);
    (ctx.providers.get as ReturnType<typeof vi.fn>).mockReturnValue(provider);

    await processJob(ctx, { jobId: job.id });

    const createMock = (ctx.prisma as unknown as {
      design: { create: ReturnType<typeof vi.fn> };
    }).design.create;
    expect(createMock).toHaveBeenCalledTimes(1);
    const data = createMock.mock.calls[0]![0].data as {
      provenance: string;
      metrics: Record<string, unknown>;
    };
    // Provenance defaults to real for the worker path.
    expect(data.provenance).toBe('real');
    // Metrics canonicalised to mixed-case labels the UI expects.
    expect(data.metrics.ipTM).toBe(0.8);
    expect(data.metrics.ipSAE).toBe(0.7);
    expect(data.metrics).not.toHaveProperty('iptm');
    // Out-of-range pLDDT (140 > 100) dropped, not persisted.
    expect(data.metrics).not.toHaveProperty('pLDDT');
    // A validation warning marker is recorded when something was dropped.
    expect(data.metrics.validation).toBe('warn');
  });

  it('preserves provenance=stub when the incoming metrics carry provenance:stub', async () => {
    const job = mkJob({ seedsRequested: 1 });
    const ctx = mkContext();
    (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.set(job.id, job);

    const provider = mkProvider([
      {
        seed: 1,
        // The Modal stub stamps provenance:'stub' into metrics.
        metrics: { iptm: 0.6, provenance: 'stub' } as unknown as Record<string, number>,
      },
    ]);
    (ctx.providers.get as ReturnType<typeof vi.fn>).mockReturnValue(provider);

    await processJob(ctx, { jobId: job.id });

    const createMock = (ctx.prisma as unknown as {
      design: { create: ReturnType<typeof vi.fn> };
    }).design.create;
    const data = createMock.mock.calls[0]![0].data as { provenance: string };
    expect(data.provenance).toBe('stub');
  });
});

describe('processJob — user error', () => {
  it('fails non-retryably when a provider emits a duplicate seed', async () => {
    const job = mkJob({
      seedsRequested: 2,
      params: { targetPdb: '5MV5', seeds: [1, 2], numDesigns: 2 },
    });
    const ctx = mkContext();
    (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.set(job.id, job);
    (ctx.providers.get as ReturnType<typeof vi.fn>).mockReturnValue(
      mkProvider([
        { seed: 1, metrics: {} },
        { seed: 1, metrics: {} },
      ]),
    );

    const result = await processJob(ctx, { jobId: job.id });

    expect(result).toMatchObject({
      outcome: 'failed',
      retryable: false,
      errorCode: 'INVALID_OUTPUT',
      seedsCompleted: 1,
    });
  });

  it('does not mark retryable when the error code is a user error', async () => {
    const job = mkJob();
    const ctx = mkContext();
    (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.set(job.id, job);

    const provider = mkProvider(
      [{ seed: 1, metrics: { ipsae: 0.8 } }],
      { throwAfter: 0, errorCode: 'INVALID_INPUT' },
    );
    (ctx.providers.get as ReturnType<typeof vi.fn>).mockReturnValue(provider);

    const result = await processJob(ctx, { jobId: job.id });
    expect(result.outcome).toBe('failed');
    expect(result.retryable).toBe(false);
  });

  it('refunds the unused GPU estimate with an explicit numeric SQL cast', async () => {
    const job = mkJob({ seedsRequested: 1 });
    const ctx = mkContext();
    (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.set(job.id, job);
    const prisma = ctx.prisma as unknown as {
      gpuSpend: {
        findFirst: ReturnType<typeof vi.fn>;
        update: ReturnType<typeof vi.fn>;
      };
      $executeRawUnsafe: ReturnType<typeof vi.fn>;
    };
    prisma.gpuSpend.findFirst.mockResolvedValue({
      id: 1,
      estimatedUsd: '2.5',
      gpuType: 'A100',
    });
    (ctx.providers.get as ReturnType<typeof vi.fn>).mockReturnValue(
      mkProvider([{ seed: 1, metrics: {} }], { throwAfter: 0, errorCode: 'INVALID_INPUT' }),
    );

    await processJob(ctx, { jobId: job.id });

    expect(prisma.gpuSpend.update).toHaveBeenCalledWith({
      where: { id: 1 },
      data: { actualUsd: expect.objectContaining({}) },
    });
    expect(prisma.$executeRawUnsafe).toHaveBeenCalledWith(
      expect.stringContaining('$1::numeric'),
      '-2.5',
      'org-1',
    );
  });

  it('does not refund an already reconciled failed attempt twice', async () => {
    const job = mkJob({ seedsRequested: 1 });
    const ctx = mkContext();
    (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.set(job.id, job);
    const prisma = ctx.prisma as unknown as {
      gpuSpend: { findFirst: ReturnType<typeof vi.fn> };
      $executeRawUnsafe: ReturnType<typeof vi.fn>;
    };
    prisma.gpuSpend.findFirst.mockResolvedValue({
      id: 1,
      estimatedUsd: '2.5',
      actualUsd: '0',
      gpuType: 'A100',
    });
    (ctx.providers.get as ReturnType<typeof vi.fn>).mockReturnValue(
      mkProvider([{ seed: 1, metrics: {} }], { throwAfter: 0, errorCode: 'INVALID_INPUT' }),
    );

    await processJob(ctx, { jobId: job.id });

    expect(prisma.$executeRawUnsafe).not.toHaveBeenCalled();
  });
});


describe('processJob — cancellation before worker claim', () => {
  it.each(['cancelled', 'cancelling'])('never dispatches %s queued work', async status => {
    const ctx = mkContext();
    (ctx as unknown as { __jobs: Map<string, JobRow> }).__jobs.set('job-1', mkJob({ status }));
    const result = await processJob(ctx, { jobId: 'job-1' });
    expect(result.outcome).toBe('cancelled');
    expect(ctx.providers.get).not.toHaveBeenCalled();
    expect(ctx.transitionJob).not.toHaveBeenCalledWith('job-1', 'preparing');
  });
});
