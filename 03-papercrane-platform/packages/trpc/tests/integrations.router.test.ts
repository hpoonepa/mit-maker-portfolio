import { describe, it, expect, vi } from 'vitest';
import { appRouter } from '../src/routers/index.js';
import { createInnerContext } from '../src/context.js';
import type { AuthContext } from '../src/context.js';

/**
 * Integrations router (Wave 14) — Slack/Discord webhook URL connections.
 *
 * Smoke contract:
 *   - list rejects unauthenticated callers
 *   - connect validates the URL shape (Slack vs Discord)
 *   - connect persists with org scoping + default events
 *   - duplicate (P2002) → CONFLICT
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

function makeCaller(integration: Record<string, ReturnType<typeof vi.fn>>) {
  const withRlsUser = vi.fn(async (_p, uid, fn) => {
    expect(uid).toBe(USER_ID);
    return fn({ integration });
  });
  return appRouter.createCaller(
    createInnerContext({
      auth: AUTH,
      prisma: {} as never,
      withRlsUser: withRlsUser as never,
    }),
  );
}

describe('integrations.list', () => {
  it('rejects unauthenticated callers', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: null }));
    await expect(caller.integrations.list()).rejects.toThrow(
      /unauthori[sz]ed/i,
    );
  });

  it('queries integrations scoped to the caller orgId', async () => {
    const findMany = vi.fn().mockResolvedValue([]);
    const caller = makeCaller({ findMany });
    await caller.integrations.list();
    const arg = findMany.mock.calls[0]![0] as { where: { orgId: string } };
    expect(arg.where.orgId).toBe(ORG_ID);
  });
});

describe('integrations.connect', () => {
  it('rejects a Slack integration with a non-Slack URL', async () => {
    const create = vi.fn();
    const caller = makeCaller({ create });
    await expect(
      caller.integrations.connect({
        kind: 'slack',
        name: 'Alerts',
        webhookUrl: 'https://discord.com/api/webhooks/1/abc',
      }),
    ).rejects.toThrow(/slack/i);
    expect(create).not.toHaveBeenCalled();
  });

  it('rejects a Discord integration with a non-Discord URL', async () => {
    const create = vi.fn();
    const caller = makeCaller({ create });
    await expect(
      caller.integrations.connect({
        kind: 'discord',
        name: 'Alerts',
        webhookUrl: 'https://hooks.slack.com/services/T/B/X',
      }),
    ).rejects.toThrow(/discord/i);
  });

  it('persists a Slack integration with default events', async () => {
    const created = {
      id: 'int1',
      orgId: ORG_ID,
      kind: 'slack',
      name: 'Alerts',
      createdAt: new Date('2026-04-25T12:00:00Z'),
      channels: [
        {
          id: 'ch1',
          integrationId: 'int1',
          webhookUrl: 'https://hooks.slack.com/services/T/B/X',
          events: ['job.completed', 'job.failed'],
          muted: false,
          capWarningPct: 80,
          createdAt: new Date('2026-04-25T12:00:00Z'),
        },
      ],
    };
    const create = vi.fn().mockResolvedValue(created);
    const caller = makeCaller({ create });
    const out = await caller.integrations.connect({
      kind: 'slack',
      name: 'Alerts',
      webhookUrl: 'https://hooks.slack.com/services/T/B/X',
    });
    expect(out.id).toBe('int1');
    expect(out.kind).toBe('slack');
    const data = create.mock.calls[0]![0]!.data as {
      orgId: string;
      kind: string;
      channels: { create: Array<{ webhookUrl: string; events: string[] }> };
    };
    expect(data.orgId).toBe(ORG_ID);
    expect(data.kind).toBe('slack');
    expect(data.channels.create[0]!.events.length).toBeGreaterThan(0);
  });

  it('maps prisma P2002 unique-violation to CONFLICT', async () => {
    const create = vi.fn().mockRejectedValue(
      Object.assign(new Error('unique'), { code: 'P2002' }),
    );
    const caller = makeCaller({ create });
    await expect(
      caller.integrations.connect({
        kind: 'slack',
        name: 'Alerts',
        webhookUrl: 'https://hooks.slack.com/services/T/B/Y',
      }),
    ).rejects.toThrow(/already|conflict|exists/i);
  });
});
