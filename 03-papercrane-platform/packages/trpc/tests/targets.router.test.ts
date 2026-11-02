import { describe, expect, it, vi } from 'vitest';
import { appRouter } from '../src/routers/index.js';
import { createInnerContext } from '../src/context.js';
import type { AuthContext } from '../src/context.js';

const USER_ID = '00000000-0000-4000-8000-000000000001';
const ORG_ID = '00000000-0000-4000-8000-00000000aaaa';
const TARGET_ID = '00000000-0000-4000-8000-000000000701';

const AUTH: AuthContext = {
  kind: 'user',
  userId: USER_ID,
  orgId: ORG_ID,
  orgSlug: 'acme',
  tier: 'pro',
  scopes: ['*'],
};

function targetRow(overrides: Record<string, unknown> = {}) {
  return {
    id: TARGET_ID,
    orgId: ORG_ID,
    projectId: null,
    name: 'PD-L1',
    pdbId: '5J89',
    artifactKey: `orgs/${ORG_ID}/uploads/pd-l1.cif`,
    checksum: 'abc123',
    hotspots: [],
    createdAt: new Date('2026-07-22T12:00:00.000Z'),
    ...overrides,
  };
}

describe('targets.get', () => {
  it('returns a signed structure URL for the org-scoped artifact', async () => {
    const findFirst = vi.fn().mockResolvedValue(targetRow());
    const presignGet = vi.fn().mockResolvedValue('https://r2.example/signed-target');
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        presignGet,
        withRlsUser: vi.fn(async (_prisma, userId, fn) => {
          expect(userId).toBe(USER_ID);
          return fn({ target: { findFirst } });
        }) as never,
      }),
    );

    const result = await caller.targets.get({ id: TARGET_ID });

    expect(findFirst).toHaveBeenCalledWith({
      where: { id: TARGET_ID, orgId: ORG_ID },
    });
    expect(presignGet).toHaveBeenCalledWith(
      `orgs/${ORG_ID}/uploads/pd-l1.cif`,
      15 * 60,
    );
    expect(result.structureUrl).toBe('https://r2.example/signed-target');
  });
});

describe('targets.updateHotspots', () => {
  it('rejects unauthenticated callers', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: null }));
    await expect(
      caller.targets.updateHotspots({ targetId: TARGET_ID, hotspots: [] }),
    ).rejects.toThrow(/unauthori[sz]ed/i);
  });

  it('persists sorted hotspot payloads on the authenticated org target', async () => {
    const findFirst = vi.fn().mockResolvedValue({ id: TARGET_ID });
    const update = vi.fn().mockResolvedValue(
      targetRow({ hotspots: [{ chain: 'A', residues: [41, 56, 115] }] }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: vi.fn(async (_prisma, _userId, fn) =>
          fn({ target: { findFirst, update } }),
        ) as never,
      }),
    );

    const hotspots = [{ chain: 'A', residues: [41, 56, 115] }];
    const result = await caller.targets.updateHotspots({
      targetId: TARGET_ID,
      hotspots,
    });

    expect(findFirst).toHaveBeenCalledWith({
      where: { id: TARGET_ID, orgId: ORG_ID },
    });
    expect(update).toHaveBeenCalledWith({
      where: { id: TARGET_ID, orgId: ORG_ID },
      data: { hotspots },
    });
    expect(result.target.hotspots).toEqual(hotspots);
  });

  it('allows clearing every saved hotspot', async () => {
    const update = vi.fn().mockResolvedValue(targetRow({ hotspots: [] }));
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: vi.fn(async (_prisma, _userId, fn) =>
          fn({
            target: {
              findFirst: vi.fn().mockResolvedValue({ id: TARGET_ID }),
              update,
            },
          }),
        ) as never,
      }),
    );

    await caller.targets.updateHotspots({ targetId: TARGET_ID, hotspots: [] });

    expect(update).toHaveBeenCalledWith(
      expect.objectContaining({ data: { hotspots: [] } }),
    );
  });

  it('does not update a target outside the caller org', async () => {
    const update = vi.fn();
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: vi.fn(async (_prisma, _userId, fn) =>
          fn({
            target: {
              findFirst: vi.fn().mockResolvedValue(null),
              update,
            },
          }),
        ) as never,
      }),
    );

    await expect(
      caller.targets.updateHotspots({
        targetId: TARGET_ID,
        hotspots: [{ chain: 'A', residues: [41] }],
      }),
    ).rejects.toThrow(/target not found/i);
    expect(update).not.toHaveBeenCalled();
  });

  it('rejects selections above the 20-residue product cap', async () => {
    const caller = appRouter.createCaller(
      createInnerContext({ auth: AUTH, prisma: {} as never }),
    );

    await expect(
      caller.targets.updateHotspots({
        targetId: TARGET_ID,
        hotspots: [{
          chain: 'A',
          residues: Array.from({ length: 21 }, (_, index) => index + 1),
        }],
      }),
    ).rejects.toThrow(/at most 20/i);
  });
});

it('filters targets by project without dropping organization isolation', async () => {
  const projectId = '00000000-0000-4000-8000-000000000123';
  const findMany = vi.fn().mockResolvedValue([]);
  const caller = appRouter.createCaller(createInnerContext({ auth: AUTH, prisma: {} as never,
    withRlsUser: vi.fn(async (_p, _u, fn) => fn({ target: { findMany } })) as never }));
  await caller.targets.list({ projectId });
  expect(findMany).toHaveBeenCalledWith(expect.objectContaining({ where: { orgId: ORG_ID, projectId } }));
});
