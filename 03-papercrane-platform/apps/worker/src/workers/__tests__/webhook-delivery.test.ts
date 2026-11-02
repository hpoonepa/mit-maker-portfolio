/**
 * Outbound webhook delivery worker.
 *
 * The processor lives at apps/worker/src/webhooks/deliveryProcessor.ts; this
 * suite is the integration-flavoured cousin of tests/webhooks/deliveryProcessor
 * — focused on the contracts exposed to the rest of the system:
 *
 *   1. Signature header is HMAC-SHA256 of `${unix-seconds}.${rawBody}` keyed
 *      by `webhook.secret` (Stripe-compatible scheme).
 *   2. Exponential backoff schedule: 60s · 2^(attempt-1), capped at 12h.
 *   3. Hard cap of 5 attempts including the initial try.
 *   4. Rolling failure window: > FAILURE_THRESHOLD failures flips
 *      `webhook.active = false`. A successful delivery resets failureCount to 0.
 *   5. Network and HTTP behaviours are fed in via injected fetch + queue +
 *      prisma mocks — no real I/O ever happens.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import crypto from 'node:crypto';
import {
  processDelivery,
  computeBackoffMs,
  MAX_ATTEMPTS,
  FAILURE_THRESHOLD,
} from '../../webhooks/deliveryProcessor';
import type { DeliveryJob, WebhookQueue } from '../../webhooks/types';

// ---- Test doubles -----------------------------------------------------------

interface DeliveryRow {
  id: string;
  webhookId: string;
  eventType: string;
  payload: unknown;
  attempt: number;
  statusCode: number | null;
  responseBody: string | null;
}
interface WebhookRow {
  id: string;
  url: string;
  secret: string;
  active: boolean;
  failureCount: number;
  lastDeliveredAt: Date | null;
  lastStatusCode: number | null;
}

function mkPrisma(delivery: DeliveryRow, webhook: WebhookRow) {
  const w = new Map([[webhook.id, webhook]]);
  const d = new Map([[delivery.id, delivery]]);
  return {
    state: { w, d },
    client: {
      webhookDelivery: {
        findUnique: vi.fn(async ({ where }: { where: { id: string } }) => d.get(where.id) ?? null),
        update: vi.fn(async ({ where, data }: { where: { id: string }; data: Partial<DeliveryRow> }) => {
          const cur = d.get(where.id)!;
          const next = { ...cur, ...data };
          d.set(where.id, next);
          return next;
        }),
      },
      webhook: {
        findUnique: vi.fn(async ({ where }: { where: { id: string } }) => w.get(where.id) ?? null),
        update: vi.fn(
          async ({ where, data }: { where: { id: string }; data: Record<string, unknown> }) => {
            const cur = w.get(where.id)!;
            const resolved: Record<string, unknown> = {};
            for (const [k, v] of Object.entries(data)) {
              if (v && typeof v === 'object' && 'increment' in (v as object)) {
                const prev = (cur as unknown as Record<string, number>)[k] ?? 0;
                resolved[k] = prev + (v as { increment: number }).increment;
              } else {
                resolved[k] = v;
              }
            }
            const next = { ...cur, ...resolved } as WebhookRow;
            w.set(where.id, next);
            return next;
          },
        ),
      },
    },
  };
}

interface QueueAdd {
  name: string;
  data: DeliveryJob;
  opts?: { delay?: number };
}

function mkQueue(): WebhookQueue & { __adds: QueueAdd[] } {
  const adds: QueueAdd[] = [];
  const q: WebhookQueue & { __adds: QueueAdd[] } = {
    __adds: adds,
    async add(name, data, opts) {
      adds.push({ name, data: data as DeliveryJob, opts });
      return { id: `${data.deliveryId}:${data.attempt}` };
    },
  };
  return q;
}

const mkLogger = () =>
  ({
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  }) as never;

function mkResponse(status: number, body = ''): Response {
  return new Response(body, { status });
}

// ---- Backoff schedule -------------------------------------------------------

describe('computeBackoffMs — exponential schedule, 12h ceiling', () => {
  it('attempt 1 → 60s, attempt 2 → 2m, attempt 3 → 4m, attempt 4 → 8m', () => {
    expect(computeBackoffMs(1)).toBe(60 * 1000);
    expect(computeBackoffMs(2)).toBe(120 * 1000);
    expect(computeBackoffMs(3)).toBe(240 * 1000);
    expect(computeBackoffMs(4)).toBe(480 * 1000);
  });

  it('caps at 12h (43_200_000 ms) once 60·2^(n-1) > 43_200', () => {
    // 60·2^9 = 30_720s — still under 43_200 (attempt 10 not yet capped).
    // 60·2^10 = 61_440s — first attempt to exceed cap is n=11.
    expect(computeBackoffMs(10)).toBe(30_720 * 1000);
    expect(computeBackoffMs(11)).toBe(43_200 * 1000);
    expect(computeBackoffMs(50)).toBe(43_200 * 1000);
    expect(computeBackoffMs(100)).toBe(43_200 * 1000);
  });

  it('hard cap on attempts is 5 (initial + 4 retries)', () => {
    expect(MAX_ATTEMPTS).toBe(5);
  });
});

// ---- Signature header -------------------------------------------------------

describe('processDelivery — HMAC-SHA256 signature header', () => {
  it('sends X-PaperCrane-Signature with HMAC over `${t}.${rawBody}`', async () => {
    const payload = { hello: 'world', n: 42 };
    const secret = 'whsec_super_secret';
    const delivery: DeliveryRow = {
      id: 'd1',
      webhookId: 'w1',
      eventType: 'job.completed',
      payload,
      attempt: 1,
      statusCode: null,
      responseBody: null,
    };
    const webhook: WebhookRow = {
      id: 'w1',
      url: 'https://customer.example/hooks',
      secret,
      active: true,
      failureCount: 0,
      lastDeliveredAt: null,
      lastStatusCode: null,
    };
    const { client } = mkPrisma(delivery, webhook);
    const queue = mkQueue();
    const fetchMock = vi.fn(async () => mkResponse(200, 'ok'));

    await processDelivery(
      { deliveryId: 'd1', attempt: 1 },
      {
        prisma: client as never,
        queue,
        logger: mkLogger(),
        fetch: fetchMock as never,
        timeoutMs: 5_000,
      },
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const call = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const [url, init] = call;
    expect(url).toBe('https://customer.example/hooks');

    const headers = init.headers as Record<string, string>;
    expect(headers['X-PaperCrane-Event']).toBe('job.completed');
    expect(headers['X-PaperCrane-Delivery']).toBe('d1');

    // Signature format: t=<unix>,v1=<hex>
    const sig = headers['X-PaperCrane-Signature']!;
    expect(sig).toMatch(/^t=\d+,v1=[0-9a-f]{64}$/);

    const m = sig.match(/^t=(\d+),v1=([0-9a-f]{64})$/)!;
    const t = m[1]!;
    const v1 = m[2]!;
    const rawBody = JSON.stringify(payload);
    const expected = crypto
      .createHmac('sha256', secret)
      .update(`${t}.${rawBody}`)
      .digest('hex');
    expect(v1).toBe(expected);
  });

  it('refuses to deliver to inactive webhooks (no fetch issued)', async () => {
    const { client } = mkPrisma(
      {
        id: 'd1',
        webhookId: 'w1',
        eventType: 'job.completed',
        payload: {},
        attempt: 1,
        statusCode: null,
        responseBody: null,
      },
      {
        id: 'w1',
        url: 'https://x',
        secret: 's',
        active: false,
        failureCount: 0,
        lastDeliveredAt: null,
        lastStatusCode: null,
      },
    );
    const fetchMock = vi.fn();
    await processDelivery(
      { deliveryId: 'd1', attempt: 1 },
      {
        prisma: client as never,
        queue: mkQueue(),
        logger: mkLogger(),
        fetch: fetchMock as never,
        timeoutMs: 1_000,
      },
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// ---- Retry + backoff path ---------------------------------------------------

describe('processDelivery — retry on transient failure', () => {
  let webhook: WebhookRow;
  let delivery: DeliveryRow;

  beforeEach(() => {
    delivery = {
      id: 'd1',
      webhookId: 'w1',
      eventType: 'job.completed',
      payload: { ok: 1 },
      attempt: 1,
      statusCode: null,
      responseBody: null,
    };
    webhook = {
      id: 'w1',
      url: 'https://customer.example',
      secret: 's',
      active: true,
      failureCount: 0,
      lastDeliveredAt: null,
      lastStatusCode: null,
    };
  });

  it('on 503, enqueues attempt 2 with 60s delay and bumps failureCount', async () => {
    const { client, state } = mkPrisma(delivery, webhook);
    const queue = mkQueue();
    const fetchMock = vi.fn(async () => mkResponse(503, 'down'));

    await processDelivery(
      { deliveryId: 'd1', attempt: 1 },
      {
        prisma: client as never,
        queue,
        logger: mkLogger(),
        fetch: fetchMock as never,
        timeoutMs: 1_000,
      },
    );

    expect(queue.__adds).toHaveLength(1);
    const enq = queue.__adds[0]!;
    expect(enq.data).toEqual({ deliveryId: 'd1', attempt: 2 });
    expect(enq.opts?.delay).toBe(60 * 1000);
    expect(state.w.get('w1')!.failureCount).toBe(1);
  });

  it('on network error (fetch throws), enqueues retry — treats as transient', async () => {
    const { client } = mkPrisma(delivery, webhook);
    const queue = mkQueue();
    const fetchMock = vi.fn(async () => {
      throw new Error('ECONNRESET');
    });

    await processDelivery(
      { deliveryId: 'd1', attempt: 1 },
      {
        prisma: client as never,
        queue,
        logger: mkLogger(),
        fetch: fetchMock as never,
        timeoutMs: 1_000,
      },
    );

    expect(queue.__adds).toHaveLength(1);
    expect(queue.__adds[0]!.data.attempt).toBe(2);
  });

  it('on 4xx (non-408/429), does NOT enqueue retry — receiver said "malformed"', async () => {
    const { client } = mkPrisma(delivery, webhook);
    const queue = mkQueue();
    const fetchMock = vi.fn(async () => mkResponse(400, 'bad request'));

    await processDelivery(
      { deliveryId: 'd1', attempt: 1 },
      {
        prisma: client as never,
        queue,
        logger: mkLogger(),
        fetch: fetchMock as never,
        timeoutMs: 1_000,
      },
    );

    expect(queue.__adds).toHaveLength(0);
  });

  it('does NOT enqueue retry past MAX_ATTEMPTS (attempt 5 is terminal)', async () => {
    const { client } = mkPrisma(delivery, webhook);
    const queue = mkQueue();
    const fetchMock = vi.fn(async () => mkResponse(500, 'still bad'));

    await processDelivery(
      { deliveryId: 'd1', attempt: MAX_ATTEMPTS },
      {
        prisma: client as never,
        queue,
        logger: mkLogger(),
        fetch: fetchMock as never,
        timeoutMs: 1_000,
      },
    );

    expect(queue.__adds).toHaveLength(0);
  });
});

// ---- Rolling failure window -------------------------------------------------

describe('processDelivery — rolling failure window circuit breaker', () => {
  it('disables webhook once failureCount > FAILURE_THRESHOLD', async () => {
    const delivery: DeliveryRow = {
      id: 'd1',
      webhookId: 'w1',
      eventType: 'job.completed',
      payload: {},
      attempt: 1,
      statusCode: null,
      responseBody: null,
    };
    const webhook: WebhookRow = {
      id: 'w1',
      url: 'https://x',
      secret: 's',
      active: true,
      // Already at threshold — this failure pushes us PAST it.
      failureCount: FAILURE_THRESHOLD,
      lastDeliveredAt: null,
      lastStatusCode: null,
    };
    const { client, state } = mkPrisma(delivery, webhook);
    const fetchMock = vi.fn(async () => mkResponse(500));

    await processDelivery(
      { deliveryId: 'd1', attempt: 1 },
      {
        prisma: client as never,
        queue: mkQueue(),
        logger: mkLogger(),
        fetch: fetchMock as never,
        timeoutMs: 1_000,
      },
    );

    const after = state.w.get('w1')!;
    expect(after.failureCount).toBe(FAILURE_THRESHOLD + 1);
    expect(after.active).toBe(false);
  });

  it('does NOT disable while failureCount stays at-or-below threshold', async () => {
    const { client, state } = mkPrisma(
      {
        id: 'd1',
        webhookId: 'w1',
        eventType: 'job.completed',
        payload: {},
        attempt: 1,
        statusCode: null,
        responseBody: null,
      },
      {
        id: 'w1',
        url: 'https://x',
        secret: 's',
        active: true,
        failureCount: 0,
        lastDeliveredAt: null,
        lastStatusCode: null,
      },
    );
    const fetchMock = vi.fn(async () => mkResponse(503));

    await processDelivery(
      { deliveryId: 'd1', attempt: 1 },
      {
        prisma: client as never,
        queue: mkQueue(),
        logger: mkLogger(),
        fetch: fetchMock as never,
        timeoutMs: 1_000,
      },
    );

    expect(state.w.get('w1')!.active).toBe(true);
    expect(state.w.get('w1')!.failureCount).toBe(1);
  });

  it('success path resets failureCount to 0 and stamps lastDeliveredAt', async () => {
    const { client, state } = mkPrisma(
      {
        id: 'd1',
        webhookId: 'w1',
        eventType: 'job.completed',
        payload: { ok: 1 },
        attempt: 1,
        statusCode: null,
        responseBody: null,
      },
      {
        id: 'w1',
        url: 'https://x',
        secret: 's',
        active: true,
        failureCount: 12, // had a rough week
        lastDeliveredAt: null,
        lastStatusCode: 500,
      },
    );
    const fetchMock = vi.fn(async () => mkResponse(202, ''));

    const before = Date.now();
    await processDelivery(
      { deliveryId: 'd1', attempt: 1 },
      {
        prisma: client as never,
        queue: mkQueue(),
        logger: mkLogger(),
        fetch: fetchMock as never,
        timeoutMs: 1_000,
      },
    );

    const after = state.w.get('w1')!;
    expect(after.failureCount).toBe(0);
    expect(after.lastStatusCode).toBe(202);
    expect(after.lastDeliveredAt).toBeInstanceOf(Date);
    expect(after.lastDeliveredAt!.getTime()).toBeGreaterThanOrEqual(before);
    expect(after.active).toBe(true);
  });
});
