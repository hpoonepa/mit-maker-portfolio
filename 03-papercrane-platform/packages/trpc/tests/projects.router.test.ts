import { describe, it, expect, vi } from 'vitest';
import { appRouter } from '../src/routers/index.js';
import { createInnerContext } from '../src/context.js';
import type { AuthContext } from '../src/context.js';

/**
 * Projects router — protected CRUD, enforces tenant isolation via
 * `withRlsUser` (we stub it here and assert it's called with the user id
 * from ctx.auth, proving downstream queries run under the correct GUC).
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

describe('projects router — RLS + auth', () => {
  it('list rejects unauthenticated callers', async () => {
    const caller = appRouter.createCaller(
      createInnerContext({ auth: null }),
    );
    await expect(caller.projects.list({})).rejects.toThrow(/unauthori[sz]ed/i);
  });

  it('list calls withRlsUser with the authenticated user id', async () => {
    const withRlsUser = vi.fn(async (_prisma, userId, fn) => {
      expect(userId).toBe(USER_ID);
      // Simulate the tx and return rows.
      return fn({
        project: {
          findMany: vi.fn().mockResolvedValue([
            {
              id: 'p1',
              orgId: ORG_ID,
              name: 'First',
              slug: 'first',
              createdAt: new Date('2026-01-01T00:00:00Z'),
              updatedAt: new Date('2026-01-01T00:00:00Z'),
            },
          ]),
        },
      });
    });

    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );

    const result = await caller.projects.list({});
    expect(withRlsUser).toHaveBeenCalledTimes(1);
    expect(result.items).toHaveLength(1);
    expect(result.items[0]!.name).toBe('First');
  });

  it('create scopes the project to the authenticated org and enforces RLS', async () => {
    const created = {
      id: 'p2',
      orgId: ORG_ID,
      name: 'New Project',
      slug: 'new-project',
      createdAt: new Date('2026-01-02T00:00:00Z'),
      updatedAt: new Date('2026-01-02T00:00:00Z'),
    };

    const createMock = vi.fn().mockResolvedValue(created);
    const findFirstMock = vi.fn().mockResolvedValue(null);
    const withRlsUser = vi.fn(async (_prisma, userId, fn) => {
      expect(userId).toBe(USER_ID);
      return fn({ project: { create: createMock, findFirst: findFirstMock } });
    });

    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );

    const out = await caller.projects.create({
      name: 'New Project',
      slug: 'new-project',
    });

    expect(createMock).toHaveBeenCalledTimes(1);
    expect(findFirstMock).toHaveBeenCalledTimes(1);
    const callArg = createMock.mock.calls[0]![0] as { data: { orgId: string } };
    expect(callArg.data.orgId).toBe(ORG_ID);
    expect(out.id).toBe('p2');
  });

  it('publishes a project with a stable opaque public id', async () => {
    const updateMock = vi.fn(async (args: unknown) => {
      const typed = args as {
        data: { isPublic: boolean; publicId: string };
      };
      return {
        isPublic: typed.data.isPublic,
        publicId: typed.data.publicId,
      };
    });
    const withRlsUser = vi.fn(async (_prisma, userId, fn) => {
      expect(userId).toBe(USER_ID);
      return fn({
        project: {
          findFirst: vi.fn().mockResolvedValue({
            publicId: null,
            isPublic: false,
            publishedAt: null,
          }),
          update: updateMock,
        },
      });
    });
    const now = new Date('2026-07-21T16:00:00.000Z');
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
        now: () => now,
      }),
    );

    const result = await caller.projects.share({ id: 'p1', isPublic: true });

    expect(result.isPublic).toBe(true);
    expect(result.publicId).toMatch(/^prj_[A-Za-z0-9_-]{24}$/);
    expect(updateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        where: { id: 'p1', orgId: ORG_ID },
        data: expect.objectContaining({
          isPublic: true,
          publicId: result.publicId,
          publishedAt: now,
        }),
      }),
    );
  });

  it('revokes a public project without rotating its opaque id', async () => {
    const stablePublicId = 'prj_1234567890abcdefghijklmn';
    const updateMock = vi.fn().mockResolvedValue({
      isPublic: false,
      publicId: stablePublicId,
    });
    const withRlsUser = vi.fn(async (_prisma, _userId, fn) =>
      fn({
        project: {
          findFirst: vi.fn().mockResolvedValue({
            publicId: stablePublicId,
            isPublic: true,
            publishedAt: new Date('2026-07-20T16:00:00.000Z'),
          }),
          update: updateMock,
        },
      }),
    );
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );

    const result = await caller.projects.share({ id: 'p1', isPublic: false });

    expect(result).toEqual({ isPublic: false, publicId: stablePublicId });
    expect(updateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          isPublic: false,
          publicId: stablePublicId,
          publishedAt: null,
        }),
      }),
    );
  });

  it('serves only the safe public report contract and ranks candidates by meta-score', async () => {
    const queryRaw = vi.fn().mockResolvedValue([
      {
        data: {
          project: {
            name: 'PD-L1 pilot',
            description: 'Computational binder campaign',
            updatedAt: '2026-07-21T16:00:00.000Z',
          },
          org: { name: 'Paper Crane Labs' },
          target: { name: 'PD-L1', pdbId: '5O45' },
          summary: { completedJobs: 2, designsGenerated: 12 },
          candidates: [
            {
              id: 'design-low',
              seed: 2,
              rank: 1,
              tool: 'boltzgen',
              provenance: 'real',
              length: 78,
              metrics: {
                computational__boltz2_min_ipsae: 0.45,
                computational__boltz2_iptm: 0.4,
              },
              sequence: 'MUST_NOT_LEAK',
            },
            {
              id: 'design-high',
              seed: 7,
              rank: 4,
              tool: 'boltzgen',
              provenance: 'real',
              length: 82,
              metrics: {
                computational__actifptm: 0.91,
                computational__interface_residues: 25,
                computational__boltz2_min_ipsae: 0.88,
                computational__boltz2_iptm: 0.84,
              },
            },
          ],
        },
      },
    ]);
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: null,
        prisma: { $queryRawUnsafe: queryRaw } as never,
      }),
    );

    const result = await caller.projects.public({
      publicId: 'prj_1234567890abcdefghijklmn',
    });

    expect(queryRaw).toHaveBeenCalledWith(
      'SELECT public.get_public_project_share($1) AS data',
      'prj_1234567890abcdefghijklmn',
    );
    expect(result.topCandidates.map((candidate) => candidate.id)).toEqual([
      'design-high',
      'design-low',
    ]);
    expect(result.topCandidates[0]?.metrics.ipTM).toBe(0.84);
    expect(result).not.toHaveProperty('members');
    expect(result.topCandidates[0]).not.toHaveProperty('sequence');
  });

  it('returns not found when a public id is revoked or unknown', async () => {
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: null,
        prisma: {
          $queryRawUnsafe: vi.fn().mockResolvedValue([{ data: null }]),
        } as never,
      }),
    );

    await expect(
      caller.projects.public({ publicId: 'prj_1234567890abcdefghijklmn' }),
    ).rejects.toMatchObject({ code: 'NOT_FOUND' });
  });
});
