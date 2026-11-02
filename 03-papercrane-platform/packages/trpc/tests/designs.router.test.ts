import { describe, it, expect, vi } from 'vitest';
import { appRouter } from '../src/routers/index.js';
import { createInnerContext } from '../src/context.js';
import type { AuthContext } from '../src/context.js';

/**
 * Designs router — read-only access scoped via withRlsUser.
 *
 * Contract under test:
 *   - listByJob/listByProject/get all reject unauthenticated callers
 *   - listByProject filters by `tool` when supplied
 *   - get returns 404 when no row matches
 *   - get attaches a presigned structureUrl when artifactKey is set
 *   - get does not throw on a realistic row (orgId/artifactKey/rank present)
 */

const USER_ID = '00000000-0000-4000-8000-000000000001';
const ORG_ID = '00000000-0000-4000-8000-00000000aaaa';

const AUTH: AuthContext = {
  kind: 'user',
  userId: USER_ID,
  orgId: ORG_ID,
  orgSlug: 'acme',
  tier: 'pro',
  scopes: ['*'],
};

/**
 * NB: DesignResultSchema is strict — only the keys listed here are allowed
 * in the procedure output. The router does not reshape, so tests must mirror
 * the wire shape exactly. Extra DB columns (orgId, structureKey, …) need to
 * be set on the row but stripped from the typed output by the router (see
 * `get` which ignores them) or kept off `listByJob` results.
 */
function baseDesign(over: Record<string, unknown> = {}) {
  return {
    id: '00000000-0000-4000-8000-000000000d01',
    jobId: '00000000-0000-4000-8000-000000000a01',
    sequence: 'MKT',
    length: 3,
    seed: 0,
    metrics: { plddt: 0.9, iptm: 0.8 },
    createdAt: '2026-04-20T00:00:00Z',
    ...over,
  };
}

describe('designs.listByJob', () => {
  it('rejects unauthenticated callers', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: null }));
    await expect(
      caller.designs.listByJob({ jobId: 'j1' }),
    ).rejects.toThrow(/unauthori[sz]ed/i);
  });

  it('filters designs by jobId + orgId under RLS', async () => {
    const findMany = vi.fn().mockResolvedValue([baseDesign()]);
    const withRlsUser = vi.fn(async (_p, uid, fn) => {
      expect(uid).toBe(USER_ID);
      return fn({ design: { findMany } });
    });
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    const out = await caller.designs.listByJob({ jobId: 'j1' });
    expect(out.items).toHaveLength(1);
    expect(out.items[0]!.metaScore).toMatchObject({
      status: 'scored',
      priorSource: 'observed_metric_fallback',
      experimental: true,
    });
    const where = (findMany.mock.calls[0]![0] as { where: { jobId: string; orgId: string } }).where;
    expect(where.jobId).toBe('j1');
    expect(where.orgId).toBe(ORG_ID);
  });

  it('presigns structures only when the caller requests viewer URLs', async () => {
    const findMany = vi.fn().mockResolvedValue([
      baseDesign({ artifactKey: 'orgs/acme/jobs/j1/designs/1.cif' }),
    ]);
    const presignGet = vi.fn(async (key: string) => `https://r2.example/${key}`);
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: vi.fn(async (_p, _uid, fn) =>
          fn({ design: { findMany } }),
        ) as never,
        presignGet,
      }),
    );

    const out = await caller.designs.listByJob({
      jobId: 'j1',
      includeStructureUrls: true,
    });

    expect(out.items[0]?.structureUrl).toBe(
      'https://r2.example/orgs/acme/jobs/j1/designs/1.cif',
    );
    expect(presignGet).toHaveBeenCalledTimes(1);
  });
});

describe('designs.listByProject', () => {
  it('passes the tool filter through to prisma when supplied', async () => {
    const findMany = vi.fn().mockResolvedValue([
      { ...baseDesign(), job: { tool: 'rfdiffusion', projectId: 'p1' } },
    ]);
    const withRlsUser = vi.fn(async (_p, _uid, fn) =>
      fn({ design: { findMany } }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    const out = await caller.designs.listByProject({
      projectId: 'p1',
      tool: 'rfdiffusion',
    });
    expect(out.items).toHaveLength(1);
    expect(out.items[0]!.tool).toBe('rfdiffusion');
    const args = findMany.mock.calls[0]![0] as { where: { job: { tool?: string } } };
    expect(args.where.job.tool).toBe('rfdiffusion');
    expect(findMany).toHaveBeenCalledWith(expect.objectContaining({
      orderBy: [{ createdAt: 'desc' }, { id: 'desc' }],
    }));
  });

  it('omits the tool filter when not supplied', async () => {
    const findMany = vi.fn().mockResolvedValue([]);
    const withRlsUser = vi.fn(async (_p, _uid, fn) =>
      fn({ design: { findMany } }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    await caller.designs.listByProject({ projectId: 'p1' });
    const args = findMany.mock.calls[0]![0] as { where: { job: Record<string, unknown> } };
    expect(args.where.job.tool).toBeUndefined();
  });
});

describe('designs.decisionReport', () => {
  it('builds an org-scoped report with scorer provenance', async () => {
    const findFirst = vi.fn().mockResolvedValue({
      id: '00000000-0000-4000-8000-000000000a01',
      status: 'succeeded',
      tool: 'bindcraft',
      toolVersion: '1.0.0',
      adapterVersion: 'adapter-1',
      imageDigest: 'sha256:abc',
      params: { targetPdb: '5G51' },
      seedsRequested: 1,
      seedsConsumed: 1,
      target: { name: 'Deformed wing virus VP3', pdbId: '5G51' },
      designs: [
        baseDesign({
          metrics: {
            computational__boltz2_min_ipsae: 0.84,
            computational__interface_residues: 22,
          },
        }),
      ],
    });
    const withRlsUser = vi.fn(async (_p, _uid, fn) => fn({ job: { findFirst } }));
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );

    const out = await caller.designs.decisionReport({ jobId: 'j1' });

    expect(out.methodology).toMatchObject({ evidenceType: 'computational', experimental: true });
    expect(out.candidates[0]?.metaScore.targetKey).toBe('5G51');
    const args = findFirst.mock.calls[0]![0] as { where: { id: string; orgId: string } };
    expect(args.where).toEqual({ id: 'j1', orgId: ORG_ID });
  });
});

describe('designs.get', () => {
  it('throws NOT_FOUND when no row matches', async () => {
    const findFirst = vi.fn().mockResolvedValue(null);
    const withRlsUser = vi.fn(async (_p, _uid, fn) =>
      fn({ design: { findFirst } }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    await expect(caller.designs.get({ id: 'missing' })).rejects.toThrow(
      /not.?found/i,
    );
  });

  it('presigns artifactKey and returns a defined structureUrl', async () => {
    const findFirst = vi.fn().mockResolvedValue({
      ...baseDesign(),
      orgId: ORG_ID,
      artifactKey: 'orgs/o1/jobs/j1/designs/0.cif',
      rank: 1,
      job: { tool: 'rfdiffusion', projectId: 'p1' },
    });
    const withRlsUser = vi.fn(async (_p, _uid, fn) =>
      fn({ design: { findFirst } }),
    );
    const presignGet = vi.fn(async (key: string) => `https://signed/${key}`);
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
        presignGet,
      }),
    );
    const out = await caller.designs.get({ id: 'd1' });
    // The presigner is invoked with the real artifact key, not a phantom field.
    expect(presignGet).toHaveBeenCalledWith(
      'orgs/o1/jobs/j1/designs/0.cif',
      15 * 60,
    );
    // structureUrl resolves from the real key (no longer always undefined).
    expect(out.structureUrl).toBe(
      'https://signed/orgs/o1/jobs/j1/designs/0.cif',
    );
    expect(out.structureExpiresInSec).toBe(15 * 60);
    expect(out.metaScore.status).toBe('scored');
  });

  it('uses linked target identity for a target-specific LLM prior', async () => {
    const findFirst = vi.fn().mockResolvedValue({
      ...baseDesign({ metrics: { ipsae: 0.81, interfaceSC: 0.72 } }),
      orgId: ORG_ID,
      rank: 1,
      job: {
        tool: 'boltz2',
        projectId: 'p1',
        params: { targetPdb: '5G51' },
        target: { name: 'Deformed wing virus VP3', pdbId: '5G51' },
      },
    });
    const withRlsUser = vi.fn(async (_p, _uid, fn) =>
      fn({ design: { findFirst } }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );

    const out = await caller.designs.get({ id: 'd1' });

    expect(out.metaScore).toMatchObject({
      priorSource: 'target_prior',
      targetKey: '5G51',
      experimental: true,
    });
    expect(out.metaScore.rationale).toMatch(/DWV VP3/i);
    expect(out.metaScore.contributions.length).toBeGreaterThan(0);
  });

  it('does not throw on a realistic row with orgId/artifactKey/rank present', async () => {
    // Regression: the strict GetOutput schema used to reject real DB rows
    // (extra columns orgId/artifactKey/rank), so get() threw before the
    // presigned URL ever reached the caller.
    const findFirst = vi.fn().mockResolvedValue({
      ...baseDesign(),
      orgId: ORG_ID,
      artifactKey: 'orgs/o1/jobs/j1/designs/0.cif',
      rank: 3,
      job: { tool: 'rfdiffusion', projectId: 'p1' },
    });
    const withRlsUser = vi.fn(async (_p, _uid, fn) =>
      fn({ design: { findFirst } }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    await expect(caller.designs.get({ id: 'd1' })).resolves.toMatchObject({
      id: baseDesign().id,
      structureUrl: expect.stringContaining('orgs/o1/jobs/j1/designs/0.cif'),
    });
  });

  it('normalizes the real Prisma row shape from worker metrics', async () => {
    const fixture = baseDesign();
    const findFirst = vi.fn().mockResolvedValue({
      id: fixture.id,
      jobId: fixture.jobId,
      seed: fixture.seed,
      metrics: {
        ipTM: 0.8,
        sequence: 'MKT',
        length: 3,
        validation: 'warn',
      },
      createdAt: new Date('2026-04-20T00:00:00Z'),
      orgId: ORG_ID,
      artifactKey: 'orgs/o1/jobs/j1/designs/0.cif',
      rank: 3,
      job: { tool: 'boltz2', params: { targetPdb: '9ZZZ' }, target: null },
    });
    const withRlsUser = vi.fn(async (_p, _uid, fn) =>
      fn({ design: { findFirst } }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );

    const out = await caller.designs.get({ id: 'd1' });

    expect(out.sequence).toBe('MKT');
    expect(out.length).toBe(3);
    expect(out.createdAt).toBe('2026-04-20T00:00:00.000Z');
    expect(out.metrics.validation).toBe('warn');
    expect(out.metaScore.status).toBe('scored');
  });

  it('surfaces the row provenance so the UI can banner synthetic/stub designs', async () => {
    const findFirst = vi.fn().mockResolvedValue({
      ...baseDesign(),
      orgId: ORG_ID,
      rank: 1,
      provenance: 'synthetic',
      job: { tool: 'rfdiffusion', projectId: 'p1' },
    });
    const withRlsUser = vi.fn(async (_p, _uid, fn) =>
      fn({ design: { findFirst } }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    const out = await caller.designs.get({ id: 'd1' });
    expect(out.provenance).toBe('synthetic');
  });

  it("keeps provenance unknown for rows that predate the column", async () => {
    // Legacy rows (and the strict baseDesign fixture) carry no provenance —
    // the output schema backfills 'real' so the UI never sees undefined.
    const findFirst = vi.fn().mockResolvedValue({
      ...baseDesign(),
      orgId: ORG_ID,
      rank: 1,
      job: { tool: 'rfdiffusion', projectId: 'p1' },
    });
    const withRlsUser = vi.fn(async (_p, _uid, fn) =>
      fn({ design: { findFirst } }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    const out = await caller.designs.get({ id: 'd1' });
    expect(out.provenance).toBe('unknown');
  });

  it('omits structureUrl when the row has no artifactKey', async () => {
    const findFirst = vi.fn().mockResolvedValue({
      ...baseDesign(),
      orgId: ORG_ID,
      rank: 1,
      job: { tool: 'rfdiffusion', projectId: 'p1' },
    });
    const withRlsUser = vi.fn(async (_p, _uid, fn) =>
      fn({ design: { findFirst } }),
    );
    const presignGet = vi.fn(async (key: string) => `https://signed/${key}`);
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
        presignGet,
      }),
    );
    const out = await caller.designs.get({ id: 'd1' });
    expect(presignGet).not.toHaveBeenCalled();
    expect(out.structureUrl).toBeUndefined();
    expect(out.structureExpiresInSec).toBeUndefined();
  });
});
