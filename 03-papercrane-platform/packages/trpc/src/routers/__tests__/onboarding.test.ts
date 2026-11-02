/**
 * Unit tests for the onboarding router.
 *
 * Covers:
 *   - markComplete: durable + idempotent completion
 *   - status: reads durable progress and defaults new users to welcome
 */
import { describe, it, expect, vi } from 'vitest';
import { appRouter } from '../index.js';
import { createTestContext as createInnerContext } from './_helpers.js';
import type { AuthContext } from '../../context.js';

const USER_ID = '00000000-0000-4000-8000-000000000001';
const ORG_ID = '00000000-0000-4000-8000-00000000aaaa';

const AUTH: AuthContext = {
  kind: 'user',
  userId: USER_ID,
  orgId: ORG_ID,
  orgSlug: 'acme',
  tier: 'free',
  scopes: ['*'],
};

type OnboardingRow = {
  userId: string;
  orgId: string | null;
  currentStep: string;
  persona: string | null;
  completedAt: Date | null;
  lastUpdatedAt: Date;
};

function authedCaller(initial: OnboardingRow | null = null) {
  let row = initial;
  const userOnboarding = {
    findUnique: vi.fn(async () => row),
    upsert: vi.fn(async (args: {
      update: Partial<OnboardingRow>;
      create: OnboardingRow;
    }) => {
      row = row
        ? { ...row, ...args.update }
        : { ...args.create };
      return row;
    }),
  };
  const prisma = { userOnboarding };
  const withRlsUser = vi.fn(async (
    _client: unknown,
    _userId: string,
    fn: (tx: typeof prisma) => Promise<unknown>,
  ) => fn(prisma));
  const caller = appRouter.createCaller(
    createInnerContext({
      auth: AUTH,
      prisma: prisma as never,
      withRlsUser: withRlsUser as never,
      now: () => new Date('2026-09-04T12:00:00.000Z'),
    }),
  );
  return { caller, userOnboarding, readRow: () => row };
}

describe('onboarding router — markComplete', () => {
  it('rejects unauthenticated callers', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: null }));
    await expect(caller.onboarding.markComplete()).rejects.toThrow(
      /unauthori[sz]ed/i,
    );
  });

  it('returns ok for an authenticated caller', async () => {
    const { caller, readRow } = authedCaller();
    const result = await caller.onboarding.markComplete();
    expect(result.ok).toBe(true);
    expect(readRow()).toMatchObject({
      userId: USER_ID,
      orgId: ORG_ID,
      currentStep: 'done',
      completedAt: new Date('2026-09-04T12:00:00.000Z'),
    });
  });

  it('is idempotent — repeated calls keep one completed row', async () => {
    const { caller, userOnboarding, readRow } = authedCaller();
    const a = await caller.onboarding.markComplete();
    const b = await caller.onboarding.markComplete();
    expect(a).toEqual(b);
    expect(userOnboarding.upsert).toHaveBeenCalledTimes(2);
    expect(readRow()?.currentStep).toBe('done');
    expect(readRow()?.completedAt).not.toBeNull();
  });
});

describe('onboarding router — status', () => {
  it('rejects unauthenticated callers', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: null }));
    await expect(caller.onboarding.status()).rejects.toThrow(
      /unauthori[sz]ed/i,
    );
  });

  it('returns the default status shape for new users', async () => {
    const { caller } = authedCaller();
    const result = await caller.onboarding.status();
    expect(result.step).toBe('welcome');
    expect(result.completed).toBe(false);
  });

  it('returns durable completion for returning users', async () => {
    const { caller } = authedCaller({
      userId: USER_ID,
      orgId: ORG_ID,
      currentStep: 'done',
      persona: 'grad',
      completedAt: new Date('2026-09-04T12:00:00.000Z'),
      lastUpdatedAt: new Date('2026-09-04T12:00:00.000Z'),
    });
    await expect(caller.onboarding.status()).resolves.toEqual({
      step: 'done',
      completed: true,
    });
  });
});

describe('onboarding router — progress', () => {
  it('persists a step and returns stored persona/org values', async () => {
    const { caller } = authedCaller({
      userId: USER_ID,
      orgId: ORG_ID,
      currentStep: 'welcome',
      persona: 'grad',
      completedAt: null,
      lastUpdatedAt: new Date('2026-09-04T11:00:00.000Z'),
    });
    const result = await caller.onboarding.setStep({ step: 'first-target' });
    expect(result).toEqual({
      currentStep: 'first-target',
      persona: 'grad',
      orgId: ORG_ID,
      completed: false,
    });
  });

  it('does not hide persistence failures', async () => {
    const prisma = {
      userOnboarding: {
        findUnique: vi.fn(),
        upsert: vi.fn(async () => {
          throw new Error('database unavailable');
        }),
      },
    };
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: prisma as never,
        withRlsUser: (async (_p: unknown, _u: string, fn: (tx: typeof prisma) => Promise<unknown>) =>
          fn(prisma)) as never,
      }),
    );
    await expect(
      caller.onboarding.setStep({ step: 'first-target' }),
    ).rejects.toThrow('database unavailable');
  });
});
