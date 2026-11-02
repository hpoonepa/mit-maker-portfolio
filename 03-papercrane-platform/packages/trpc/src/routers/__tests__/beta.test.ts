import { describe, expect, it, vi } from 'vitest';
import { appRouter } from '../index.js';
import { createTestContext } from './_helpers.js';
import type { AuthContext } from '../../context.js';

const USER_ID = '00000000-0000-4000-8000-000000000001';
const AUTH: AuthContext = {
  kind: 'user',
  userId: USER_ID,
  orgId: '00000000-0000-4000-8000-00000000aaaa',
  orgSlug: 'acme',
  tier: 'free',
  scopes: ['*'],
};

function claimCaller(queryResults: unknown[][]) {
  const query = vi.fn();
  for (const result of queryResults) query.mockResolvedValueOnce(result);
  const update = vi.fn(async () => ({ id: USER_ID }));
  const tx = { $queryRawUnsafe: query, user: { update } };
  const prisma = {
    $transaction: vi.fn(async (fn: (client: typeof tx) => Promise<unknown>) =>
      fn(tx),
    ),
  };
  return {
    caller: appRouter.createCaller(
      createTestContext({
        auth: AUTH,
        prisma: prisma as never,
        now: () => new Date('2026-09-04T12:00:00.000Z'),
      }),
    ),
    query,
    update,
  };
}

describe('beta.claimInvite', () => {
  it('requires an authenticated identity', async () => {
    const caller = appRouter.createCaller(createTestContext({ auth: null }));
    await expect(
      caller.beta.claimInvite({ code: 'PC-ABCD-EFGH' }),
    ).rejects.toThrow(/unauthori[sz]ed/i);
  });

  it('rejects caller-supplied user ids', async () => {
    const { caller } = claimCaller([]);
    await expect(
      caller.beta.claimInvite({
        code: 'PC-ABCD-EFGH',
        userId: '00000000-0000-4000-8000-000000000099',
      } as never),
    ).rejects.toThrow();
  });

  it('consumes a valid invite and grants durable access', async () => {
    const { caller, query, update } = claimCaller([
      [{ beta_access_granted_at: null }],
      [{ id: 'invite-1' }],
    ]);
    await expect(
      caller.beta.claimInvite({ code: 'PC-ABCD-EFGH' }),
    ).resolves.toEqual({ ok: true, reason: 'ok' });
    expect(query).toHaveBeenCalledTimes(2);
    expect(query.mock.calls[1]?.[2]).toBe(USER_ID);
    expect(update).toHaveBeenCalledWith({
      where: { id: USER_ID },
      data: { betaAccessGrantedAt: new Date('2026-09-04T12:00:00.000Z') },
    });
  });

  it('is idempotent for a user who is already admitted', async () => {
    const { caller, query, update } = claimCaller([
      [{ beta_access_granted_at: new Date('2026-09-03T12:00:00.000Z') }],
    ]);
    await expect(caller.beta.claimInvite({})).resolves.toEqual({
      ok: true,
      reason: 'ok',
    });
    expect(query).toHaveBeenCalledTimes(1);
    expect(update).not.toHaveBeenCalled();
  });

  it('requires a code for a new user', async () => {
    const { caller, update } = claimCaller([
      [{ beta_access_granted_at: null }],
    ]);
    await expect(caller.beta.claimInvite({})).resolves.toEqual({
      ok: false,
      reason: 'required',
    });
    expect(update).not.toHaveBeenCalled();
  });
});

describe('beta.accessStatus', () => {
  it('reads admission for the authenticated user', async () => {
    const findUnique = vi.fn(async () => ({
      betaAccessGrantedAt: new Date('2026-09-04T12:00:00.000Z'),
    }));
    const tx = { user: { findUnique } };
    const caller = appRouter.createCaller(
      createTestContext({
        auth: AUTH,
        prisma: tx as never,
        withRlsUser: (async (
          _client: unknown,
          _userId: string,
          fn: (client: typeof tx) => Promise<unknown>,
        ) => fn(tx)) as never,
      }),
    );
    await expect(caller.beta.accessStatus()).resolves.toEqual({ granted: true });
    expect(findUnique).toHaveBeenCalledWith({
      where: { id: USER_ID },
      select: { betaAccessGrantedAt: true },
    });
  });
});
