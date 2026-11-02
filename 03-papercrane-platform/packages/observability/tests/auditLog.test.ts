import { describe, it, expect, vi } from 'vitest';
import { logAuditEvent, extractRequestMeta } from '../src/auditLog.js';

function makePrismaMock() {
  const create = vi.fn(async (args: { data: Record<string, unknown> }) => ({
    id: '00000000-0000-0000-0000-000000000001',
    ...args.data,
    createdAt: new Date('2026-04-24T10:00:00Z'),
  }));
  return {
    auditLog: { create },
    create,
  };
}

describe('logAuditEvent', () => {
  it('inserts a row with required fields and defaults optional ones to null', async () => {
    const prisma = makePrismaMock();
    const row = await logAuditEvent(prisma as unknown as Parameters<typeof logAuditEvent>[0], {
      orgId: '11111111-1111-1111-1111-111111111111',
      userId: '22222222-2222-2222-2222-222222222222',
      action: 'api_key.created',
    });
    expect(prisma.create).toHaveBeenCalledTimes(1);
    const payload = prisma.create.mock.calls[0]![0];
    expect(payload.data).toMatchObject({
      orgId: '11111111-1111-1111-1111-111111111111',
      userId: '22222222-2222-2222-2222-222222222222',
      action: 'api_key.created',
      resourceType: null,
      resourceId: null,
      metadata: null,
      ipAddress: null,
      userAgent: null,
    });
    expect(row).toBeTruthy();
  });

  it('forwards resourceType, resourceId, and metadata when provided', async () => {
    const prisma = makePrismaMock();
    await logAuditEvent(prisma as unknown as Parameters<typeof logAuditEvent>[0], {
      orgId: 'org-1',
      action: 'webhook.created',
      resourceType: 'webhook',
      resourceId: 'wh_abc',
      metadata: { url: 'https://hooks.example/x', events: ['job.completed'] },
    });
    const data = prisma.create.mock.calls[0]![0].data as Record<string, unknown>;
    expect(data.resourceType).toBe('webhook');
    expect(data.resourceId).toBe('wh_abc');
    expect(data.metadata).toEqual({
      url: 'https://hooks.example/x',
      events: ['job.completed'],
    });
  });

  it('extracts IP + user-agent from a request-like object', async () => {
    const prisma = makePrismaMock();
    const req = {
      headers: {
        'user-agent': 'Mozilla/5.0 PaperCrane',
        'x-forwarded-for': '203.0.113.42, 10.0.0.1',
      },
      ip: '10.0.0.1',
    };
    await logAuditEvent(prisma as unknown as Parameters<typeof logAuditEvent>[0], {
      orgId: 'org-1',
      action: 'member.invited',
      req,
    });
    const data = prisma.create.mock.calls[0]![0].data as Record<string, unknown>;
    // x-forwarded-for should take precedence and use the leftmost entry.
    expect(data.ipAddress).toBe('203.0.113.42');
    expect(data.userAgent).toBe('Mozilla/5.0 PaperCrane');
  });

  it('falls back to req.ip when x-forwarded-for is missing', async () => {
    const prisma = makePrismaMock();
    await logAuditEvent(prisma as unknown as Parameters<typeof logAuditEvent>[0], {
      orgId: 'org-1',
      action: 'job.cancelled',
      req: { headers: { 'user-agent': 'curl/8.0' }, ip: '198.51.100.5' },
    });
    const data = prisma.create.mock.calls[0]![0].data as Record<string, unknown>;
    expect(data.ipAddress).toBe('198.51.100.5');
    expect(data.userAgent).toBe('curl/8.0');
  });

  it('swallows prisma errors and returns null (never throws from call sites)', async () => {
    const boom = vi.fn(async () => {
      throw new Error('db exploded');
    });
    const prisma = { auditLog: { create: boom } };
    const result = await logAuditEvent(
      prisma as unknown as Parameters<typeof logAuditEvent>[0],
      { orgId: 'org-1', action: 'api_key.revoked' },
    );
    expect(result).toBeNull();
    expect(boom).toHaveBeenCalledTimes(1);
  });

  it('rejects unknown action ids at type-check boundary (runtime guard)', async () => {
    const prisma = makePrismaMock();
    await expect(
      logAuditEvent(
        prisma as unknown as Parameters<typeof logAuditEvent>[0],
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        { orgId: 'org-1', action: 'not.a.real.action' as any },
      ),
    ).resolves.toBeNull();
    expect(prisma.create).not.toHaveBeenCalled();
  });
});

describe('extractRequestMeta', () => {
  it('returns empty meta for undefined req', () => {
    expect(extractRequestMeta(undefined)).toEqual({ ipAddress: null, userAgent: null });
  });

  it('handles arrayed x-forwarded-for correctly', () => {
    const meta = extractRequestMeta({
      headers: {
        'x-forwarded-for': ['203.0.113.1, 10.0.0.1', '10.0.0.2'],
        'user-agent': 'ua',
      },
    });
    expect(meta.ipAddress).toBe('203.0.113.1');
    expect(meta.userAgent).toBe('ua');
  });

  it('trims whitespace in forwarded-for entries', () => {
    const meta = extractRequestMeta({
      headers: { 'x-forwarded-for': '   192.0.2.9  ,  10.0.0.1  ' },
    });
    expect(meta.ipAddress).toBe('192.0.2.9');
  });
});
