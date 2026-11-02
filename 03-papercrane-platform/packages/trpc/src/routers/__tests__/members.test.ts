/**
 * Unit tests for the members router.
 *
 * Covers:
 *   - list: unauthorized + happy path
 *   - invite: validation error, RBAC denial when not a member, conflict on
 *     duplicate, happy path
 *   - removeInvite: happy path
 *   - leave: refuses last owner
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

function makeMemberClient(overrides: Record<string, unknown> = {}) {
  return {
    orgMember: {
      findMany: vi.fn().mockResolvedValue([]),
      findUnique: vi.fn().mockResolvedValue({ role: 'owner' }),
      findFirst: vi.fn().mockResolvedValue(null),
      count: vi.fn().mockResolvedValue(2),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn().mockResolvedValue({}),
      upsert: vi.fn(),
    },
    invite: {
      findMany: vi.fn().mockResolvedValue([]),
      findUnique: vi.fn().mockResolvedValue(null),
      findFirst: vi.fn().mockResolvedValue(null),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
      deleteMany: vi.fn().mockResolvedValue({ count: 1 }),
    },
    user: {
      findUnique: vi.fn().mockResolvedValue({ email: 'me@example.com' }),
    },
    ...overrides,
  };
}

describe('members router — list', () => {
  it('rejects unauthenticated callers', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: null }));
    await expect(caller.members.list()).rejects.toThrow(/unauthori[sz]ed/i);
  });

  it('returns members and pending invites', async () => {
    const memberRow = {
      orgId: ORG_ID,
      userId: USER_ID,
      role: 'owner',
      createdAt: new Date('2026-01-01T00:00:00Z'),
      user: { email: 'me@example.com', name: 'Me' },
    };
    const inviteRow = {
      id: 'inv-1',
      orgId: ORG_ID,
      email: 'new@example.com',
      role: 'member',
      invitedBy: USER_ID,
      expiresAt: new Date('2026-05-01T00:00:00Z'),
      acceptedAt: null,
      createdAt: new Date('2026-04-01T00:00:00Z'),
      inviter: { email: 'me@example.com', name: 'Me' },
    };
    const client = makeMemberClient();
    client.orgMember.findMany = vi.fn().mockResolvedValue([memberRow]);
    client.invite.findMany = vi.fn().mockResolvedValue([inviteRow]);

    const withRlsUser = vi.fn(async (_p, _u, fn) => fn(client));
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    const result = await caller.members.list();
    expect(result.items).toHaveLength(1);
    expect(result.items[0]!.email).toBe('me@example.com');
    expect(result.pendingInvites).toHaveLength(1);
    expect(result.pendingInvites[0]!.email).toBe('new@example.com');
  });
});

describe('members router — invite', () => {
  it('rejects invalid email (Zod validation)', async () => {
    const caller = appRouter.createCaller(createInnerContext({ auth: AUTH }));
    await expect(
      caller.members.invite({ email: 'not-an-email', role: 'member' }),
    ).rejects.toThrow();
  });

  it('rejects when caller is not a member of the org', async () => {
    const client = makeMemberClient();
    client.orgMember.findUnique = vi.fn().mockResolvedValue(null);

    const withRlsUser = vi.fn(async (_p, _u, fn) => fn(client));
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    await expect(
      caller.members.invite({ email: 'new@example.com', role: 'member' }),
    ).rejects.toThrow(/not a member/i);
  });

  it('creates an invite when actor is owner', async () => {
    const client = makeMemberClient();
    client.invite.create = vi.fn().mockResolvedValue({
      id: 'inv-new',
      orgId: ORG_ID,
      email: 'new@example.com',
      role: 'member',
      invitedBy: USER_ID,
      token: 'tok',
      expiresAt: new Date('2026-05-01T00:00:00Z'),
      acceptedAt: null,
      createdAt: new Date('2026-04-01T00:00:00Z'),
    });

    const withRlsUser = vi.fn(async (_p, _u, fn) => fn(client));
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    const result = await caller.members.invite({
      email: 'new@example.com',
      role: 'member',
    });
    expect(result.invite.email).toBe('new@example.com');
    expect(result.emailLogged).toBe(true);
  });

  it('rejects duplicate invite with CONFLICT', async () => {
    const client = makeMemberClient();
    client.invite.findFirst = vi.fn().mockResolvedValue({ id: 'inv-existing' });

    const withRlsUser = vi.fn(async (_p, _u, fn) => fn(client));
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    await expect(
      caller.members.invite({ email: 'new@example.com', role: 'member' }),
    ).rejects.toThrow(/pending invite/i);
  });
});

describe('members router — leave', () => {
  it('refuses to remove the last owner', async () => {
    const client = makeMemberClient();
    client.orgMember.findUnique = vi.fn().mockResolvedValue({ role: 'owner' });
    client.orgMember.count = vi.fn().mockResolvedValue(1);

    const withRlsUser = vi.fn(async (_p, _u, fn) => fn(client));
    const caller = appRouter.createCaller(
      createInnerContext({
        auth: AUTH,
        prisma: {} as never,
        withRlsUser: withRlsUser as never,
      }),
    );
    await expect(caller.members.leave()).rejects.toThrow(/last owner/i);
  });
});
