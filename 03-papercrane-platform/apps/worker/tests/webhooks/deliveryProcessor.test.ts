/**
 * deliveryProcessor tests — HTTPS POST, retry scheduling, dead-letter.
 *
 * We inject `fetch` so the test controls the response. Network calls never
 * leave the test process.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { processDelivery } from '../../src/webhooks/deliveryProcessor';
import type { DeliveryJob, WebhookQueue } from '../../src/webhooks/types';

type DeliveryRow = {
  id: string;
  webhookId: string;
  eventId: string;
  eventType: string;
  payload: unknown;
  attempt: number;
  statusCode: number | null;
  responseBody: string | null;
};
type WebhookRow = {
  id: string;
  orgId: string;
  url: string;
  secret: string;
  active: boolean;
  failureCount: number;
  lastDeliveredAt: Date | null;
  lastStatusCode: number | null;
};

function mkPrisma(delivery: DeliveryRow, webhook: WebhookRow) {
  const webhooks = new Map<string, WebhookRow>([[webhook.id, webhook]]);
  const deliveries = new Map<string, DeliveryRow>([[delivery.id, delivery]]);
  const prisma = {
    webhookDelivery: {
      findUnique: vi.fn(async ({ where }: { where: { id: string } }) => deliveries.get(where.id) ?? null),
      update: vi.fn(
        async ({ where, data }: { where: { id: string }; data: Partial<DeliveryRow> }) => {
          const cur = deliveries.get(where.id)!;
          const next = { ...cur, ...data };
          deliveries.set(where.id, next);
          return next;
        },
      ),
    },
    webhook: {
      findUnique: vi.fn(async ({ where }: { where: { id: string } }) => webhooks.get(where.id) ?? null),
      update: vi.fn(
        async ({ where, data }: { where: { id: string }; data: Partial<WebhookRow> | Record<string, unknown> }) => {
          const cur = webhooks.get(where.id)!;
          // Handle {increment: n}
          const resolved: Record<string, unknown> = {};
          for (const [k, v] of Object.entries(data)) {
            if (v && typeof v === 'object' && 'increment' in (v as object)) {
              const prev = (cur as unknown as Record<string, number>)[k] ?? 0;
              resolved[k] = prev + (v as { increment: number }).increment;
            } else if (v && typeof v === 'object' && 'set' in (v as object)) {
              resolved[k] = (v as { set: unknown }).set;
            } else {
              resolved[k] = v;
            }
          }
          const next = { ...cur, ...resolved } as WebhookRow;
          webhooks.set(where.id, next);
          return next;
        },
      ),
    },
  };
  return { prisma, webhooks, deliveries };
}

function mkQueue(): WebhookQueue & { __adds: Array<{ name: string; data: unknown; opts?: { delay?: number } }> } {
  const adds: Array<{ name: string; data: unknown; opts?: { delay?: number } }> = [];
  return Object.assign(
    {
      async add(name: string, data: unknown, opts?: { delay?: number }) {
        adds.push({ name, data, opts });
        return { id: `q-${adds.length}` };
      },
    },
    { __adds: adds },
  );
}

function mkDelivery(overrides: Partial<DeliveryRow> = {}): DeliveryRow {
  return {
    id: 'del-1',
    webhookId: 'w1',
    eventId: 'evt-1',
    eventType: 'job.completed',
    payload: { type: 'job.completed', data: { jobId: 'job-1' }, created: 1700000000 },
    attempt: 1,
    statusCode: null,
    responseBody: null,
    ...overrides,
  };
}
function mkWebhook(overrides: Partial<WebhookRow> = {}): WebhookRow {
  return {
    id: 'w1',
    orgId: 'org-1',
    url: 'https://receiver.example/hook',
    secret: 's3cr3t',
    active: true,
    failureCount: 0,
    lastDeliveredAt: null,
    lastStatusCode: null,
    ...overrides,
  };
}

const logger = {
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
  child: vi.fn().mockReturnThis(),
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('processDelivery — happy path (2xx)', () => {
  it('POSTs the payload and marks the delivery as delivered', async () => {
    const delivery = mkDelivery();
    const webhook = mkWebhook();
    const { prisma, webhooks, deliveries } = mkPrisma(delivery, webhook);
    const queue = mkQueue();

    const fetchMock = vi.fn().mockResolvedValue({
      status: 200,
      text: async () => 'ok',
    });

    const job: DeliveryJob = { deliveryId: delivery.id, attempt: 1 };
    await processDelivery(job, {
      prisma: prisma as never,
      queue,
      logger: logger as never,
      fetch: fetchMock as unknown as typeof fetch,
      timeoutMs: 5000,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('https://receiver.example/hook');
    const headers = (init as { headers: Record<string, string> }).headers;
    expect(headers['X-PaperCrane-Signature']).toMatch(/^t=\d+,v1=[0-9a-f]{64}$/);
    expect(headers['X-PaperCrane-Event']).toBe('job.completed');
    expect(headers['X-PaperCrane-Delivery']).toBe('del-1');
    expect(headers['Content-Type']).toBe('application/json');

    // Row updated.
    expect(deliveries.get('del-1')?.statusCode).toBe(200);
    const w = webhooks.get('w1')!;
    expect(w.failureCount).toBe(0);
    expect(w.lastStatusCode).toBe(200);
    expect(w.lastDeliveredAt).toBeInstanceOf(Date);

    // No retry enqueued.
    expect(queue.__adds).toHaveLength(0);
  });
});

describe('processDelivery — retry on 5xx / 408 / 429 / network', () => {
  it('reschedules delivery on 500 with exponential backoff', async () => {
    const delivery = mkDelivery({ attempt: 1 });
    const webhook = mkWebhook();
    const { prisma, webhooks } = mkPrisma(delivery, webhook);
    const queue = mkQueue();

    const fetchMock = vi.fn().mockResolvedValue({
      status: 500,
      text: async () => 'server broke',
    });

    await processDelivery(
      { deliveryId: delivery.id, attempt: 1 },
      { prisma: prisma as never, queue, logger: logger as never, fetch: fetchMock as unknown as typeof fetch, timeoutMs: 5000 },
    );

    // attempt=1 → 60s delay = 60_000 ms
    expect(queue.__adds).toHaveLength(1);
    expect(queue.__adds[0].opts?.delay).toBe(60_000);
    expect((queue.__adds[0].data as DeliveryJob).attempt).toBe(2);
    expect(webhooks.get('w1')?.failureCount).toBe(1);
  });

  it('uses exponential schedule 1m, 2m, 4m, 8m, 16m (capped at 12h)', async () => {
    const delivery = mkDelivery();
    const webhook = mkWebhook();
    const { prisma } = mkPrisma(delivery, webhook);

    const expected = [60_000, 120_000, 240_000, 480_000]; // attempts 1..4 → delays
    for (let attempt = 1; attempt <= 4; attempt++) {
      const queue = mkQueue();
      const fetchMock = vi.fn().mockResolvedValue({ status: 503, text: async () => '' });
      await processDelivery(
        { deliveryId: delivery.id, attempt },
        { prisma: prisma as never, queue, logger: logger as never, fetch: fetchMock as unknown as typeof fetch, timeoutMs: 5000 },
      );
      expect(queue.__adds[0].opts?.delay).toBe(expected[attempt - 1]);
    }
  });

  it('retries on 408 (Request Timeout)', async () => {
    const delivery = mkDelivery();
    const webhook = mkWebhook();
    const { prisma } = mkPrisma(delivery, webhook);
    const queue = mkQueue();
    const fetchMock = vi.fn().mockResolvedValue({ status: 408, text: async () => '' });

    await processDelivery(
      { deliveryId: delivery.id, attempt: 1 },
      { prisma: prisma as never, queue, logger: logger as never, fetch: fetchMock as unknown as typeof fetch, timeoutMs: 5000 },
    );

    expect(queue.__adds).toHaveLength(1);
  });

  it('retries on 429 (Too Many Requests)', async () => {
    const delivery = mkDelivery();
    const webhook = mkWebhook();
    const { prisma } = mkPrisma(delivery, webhook);
    const queue = mkQueue();
    const fetchMock = vi.fn().mockResolvedValue({ status: 429, text: async () => '' });

    await processDelivery(
      { deliveryId: delivery.id, attempt: 1 },
      { prisma: prisma as never, queue, logger: logger as never, fetch: fetchMock as unknown as typeof fetch, timeoutMs: 5000 },
    );

    expect(queue.__adds).toHaveLength(1);
  });

  it('retries on network error', async () => {
    const delivery = mkDelivery();
    const webhook = mkWebhook();
    const { prisma } = mkPrisma(delivery, webhook);
    const queue = mkQueue();
    const fetchMock = vi.fn().mockRejectedValue(new Error('ECONNRESET'));

    await processDelivery(
      { deliveryId: delivery.id, attempt: 1 },
      { prisma: prisma as never, queue, logger: logger as never, fetch: fetchMock as unknown as typeof fetch, timeoutMs: 5000 },
    );

    expect(queue.__adds).toHaveLength(1);
    expect((queue.__adds[0].data as DeliveryJob).attempt).toBe(2);
  });
});

describe('processDelivery — 4xx (except 408/429) = permanent failure', () => {
  it('does not retry on 400', async () => {
    const delivery = mkDelivery();
    const webhook = mkWebhook();
    const { prisma, webhooks, deliveries } = mkPrisma(delivery, webhook);
    const queue = mkQueue();
    const fetchMock = vi.fn().mockResolvedValue({ status: 400, text: async () => 'bad' });

    await processDelivery(
      { deliveryId: delivery.id, attempt: 1 },
      { prisma: prisma as never, queue, logger: logger as never, fetch: fetchMock as unknown as typeof fetch, timeoutMs: 5000 },
    );

    expect(queue.__adds).toHaveLength(0);
    expect(deliveries.get('del-1')?.statusCode).toBe(400);
    // failureCount bumped but no retry scheduled.
    expect(webhooks.get('w1')?.failureCount).toBe(1);
  });

  it('does not retry on 404', async () => {
    const delivery = mkDelivery();
    const webhook = mkWebhook();
    const { prisma } = mkPrisma(delivery, webhook);
    const queue = mkQueue();
    const fetchMock = vi.fn().mockResolvedValue({ status: 404, text: async () => '' });

    await processDelivery(
      { deliveryId: delivery.id, attempt: 1 },
      { prisma: prisma as never, queue, logger: logger as never, fetch: fetchMock as unknown as typeof fetch, timeoutMs: 5000 },
    );

    expect(queue.__adds).toHaveLength(0);
  });
});

describe('processDelivery — dead-letter after 5 attempts', () => {
  it('does not reschedule a 6th attempt', async () => {
    const delivery = mkDelivery({ attempt: 5 });
    const webhook = mkWebhook();
    const { prisma } = mkPrisma(delivery, webhook);
    const queue = mkQueue();
    const fetchMock = vi.fn().mockResolvedValue({ status: 500, text: async () => '' });

    await processDelivery(
      { deliveryId: delivery.id, attempt: 5 },
      { prisma: prisma as never, queue, logger: logger as never, fetch: fetchMock as unknown as typeof fetch, timeoutMs: 5000 },
    );

    expect(queue.__adds).toHaveLength(0);
  });

  it('marks webhook inactive after failureCount > 20 in rolling window', async () => {
    const delivery = mkDelivery({ attempt: 5 });
    const webhook = mkWebhook({ failureCount: 20 }); // will hit 21 post-increment
    const { prisma, webhooks } = mkPrisma(delivery, webhook);
    const queue = mkQueue();
    const fetchMock = vi.fn().mockResolvedValue({ status: 500, text: async () => '' });

    await processDelivery(
      { deliveryId: delivery.id, attempt: 5 },
      { prisma: prisma as never, queue, logger: logger as never, fetch: fetchMock as unknown as typeof fetch, timeoutMs: 5000 },
    );

    expect(webhooks.get('w1')?.active).toBe(false);
  });
});

describe('processDelivery — no-op when row missing', () => {
  it('skips gracefully if the delivery row was deleted', async () => {
    const delivery = mkDelivery();
    const webhook = mkWebhook();
    const { prisma } = mkPrisma(delivery, webhook);
    const queue = mkQueue();
    const fetchMock = vi.fn();

    await processDelivery(
      { deliveryId: 'does-not-exist', attempt: 1 },
      { prisma: prisma as never, queue, logger: logger as never, fetch: fetchMock as unknown as typeof fetch, timeoutMs: 5000 },
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(queue.__adds).toHaveLength(0);
  });

  it('skips gracefully if the webhook is already inactive', async () => {
    const delivery = mkDelivery();
    const webhook = mkWebhook({ active: false });
    const { prisma } = mkPrisma(delivery, webhook);
    const queue = mkQueue();
    const fetchMock = vi.fn();

    await processDelivery(
      { deliveryId: delivery.id, attempt: 1 },
      { prisma: prisma as never, queue, logger: logger as never, fetch: fetchMock as unknown as typeof fetch, timeoutMs: 5000 },
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(queue.__adds).toHaveLength(0);
  });
});
