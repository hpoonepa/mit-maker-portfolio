/**
 * Dispatcher tests — fan-out to matching webhooks only.
 *
 * The dispatcher is called by the job processor when a domain event fires.
 * Responsibilities:
 *   1. Query `webhook` rows where `orgId == event.orgId` AND `events` array
 *      contains `event.name` AND `active = true`.
 *   2. Create one `webhookDelivery` row per match (attempt = 1).
 *   3. Enqueue one BullMQ job per delivery on the webhook queue.
 *
 * Tests mock Prisma and the BullMQ Queue. No real Redis involved.
 */

import { describe, it, expect, vi } from 'vitest';
import { createDispatcher } from '../../src/webhooks/dispatcher';
import type { WebhookQueue } from '../../src/webhooks/types';

type WebhookRow = {
  id: string;
  orgId: string;
  url: string;
  events: string[];
  secret: string;
  active: boolean;
};

function mkPrisma(webhooks: WebhookRow[]) {
  const deliveries: Array<{ webhookId: string; eventId: string; eventType: string; payload: unknown }> = [];
  const prisma = {
    webhook: {
      findMany: vi.fn(
        async ({ where }: { where: { orgId: string; active: boolean; events: { has: string } } }) => {
          return webhooks.filter(
            (w) =>
              w.orgId === where.orgId &&
              w.active === where.active &&
              w.events.includes(where.events.has),
          );
        },
      ),
    },
    webhookDelivery: {
      create: vi.fn(async ({ data }: { data: Record<string, unknown> }) => {
        const row = { id: `del-${deliveries.length + 1}`, ...data };
        deliveries.push(row as (typeof deliveries)[number]);
        return row;
      }),
    },
  };
  return { prisma, deliveries };
}

function mkQueue(): WebhookQueue & { __adds: Array<{ name: string; data: unknown; opts?: unknown }> } {
  const adds: Array<{ name: string; data: unknown; opts?: unknown }> = [];
  const queue = {
    async add(name: string, data: unknown, opts?: unknown) {
      adds.push({ name, data, opts });
      return { id: `q-${adds.length}` };
    },
  };
  return Object.assign(queue, { __adds: adds });
}

const logger = { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn(), child: vi.fn() };

describe('dispatcher.dispatch', () => {
  it('is a no-op when no webhooks are subscribed to the org+event', async () => {
    const { prisma, deliveries } = mkPrisma([]);
    const queue = mkQueue();
    const dispatcher = createDispatcher({
      prisma: prisma as never,
      queue,
      logger: logger as never,
    });

    await dispatcher.dispatch({
      orgId: 'org-1',
      event: 'job.completed',
      payload: { jobId: 'job-1' },
    });

    expect(deliveries).toHaveLength(0);
    expect(queue.__adds).toHaveLength(0);
  });

  it('fans out to every matching webhook (3 matches → 3 deliveries + 3 enqueues)', async () => {
    const { prisma, deliveries } = mkPrisma([
      { id: 'w1', orgId: 'org-1', url: 'https://a.example/hook', events: ['job.completed'], secret: 's1', active: true },
      { id: 'w2', orgId: 'org-1', url: 'https://b.example/hook', events: ['job.completed', 'job.failed'], secret: 's2', active: true },
      { id: 'w3', orgId: 'org-1', url: 'https://c.example/hook', events: ['job.completed'], secret: 's3', active: true },
    ]);
    const queue = mkQueue();
    const dispatcher = createDispatcher({
      prisma: prisma as never,
      queue,
      logger: logger as never,
    });

    await dispatcher.dispatch({
      orgId: 'org-1',
      event: 'job.completed',
      payload: { jobId: 'job-1' },
    });

    expect(deliveries).toHaveLength(3);
    expect(queue.__adds).toHaveLength(3);
    // Each enqueue carries the deliveryId (so the processor can fetch it).
    for (const add of queue.__adds) {
      expect((add.data as { deliveryId: string }).deliveryId).toMatch(/^del-/);
    }
  });

  it('skips webhooks whose subscription list does not include the event', async () => {
    const { prisma, deliveries } = mkPrisma([
      { id: 'w1', orgId: 'org-1', url: 'https://a', events: ['job.completed'], secret: 's', active: true },
      { id: 'w2', orgId: 'org-1', url: 'https://b', events: ['design.top_hit'], secret: 's', active: true },
    ]);
    const queue = mkQueue();
    const dispatcher = createDispatcher({
      prisma: prisma as never,
      queue,
      logger: logger as never,
    });

    await dispatcher.dispatch({
      orgId: 'org-1',
      event: 'job.completed',
      payload: { jobId: 'job-1' },
    });

    expect(deliveries).toHaveLength(1);
    expect(deliveries[0].webhookId).toBe('w1');
  });

  it('skips webhooks from other orgs', async () => {
    const { prisma, deliveries } = mkPrisma([
      { id: 'w1', orgId: 'org-1', url: 'https://a', events: ['job.completed'], secret: 's', active: true },
      { id: 'w2', orgId: 'org-2', url: 'https://b', events: ['job.completed'], secret: 's', active: true },
    ]);
    const queue = mkQueue();
    const dispatcher = createDispatcher({
      prisma: prisma as never,
      queue,
      logger: logger as never,
    });

    await dispatcher.dispatch({
      orgId: 'org-1',
      event: 'job.completed',
      payload: { jobId: 'job-1' },
    });

    expect(deliveries).toHaveLength(1);
    expect(deliveries[0].webhookId).toBe('w1');
  });

  it('does not dispatch to inactive webhooks', async () => {
    const { prisma, deliveries } = mkPrisma([
      { id: 'w1', orgId: 'org-1', url: 'https://a', events: ['job.completed'], secret: 's', active: false },
    ]);
    const queue = mkQueue();
    const dispatcher = createDispatcher({
      prisma: prisma as never,
      queue,
      logger: logger as never,
    });

    await dispatcher.dispatch({
      orgId: 'org-1',
      event: 'job.completed',
      payload: { jobId: 'job-1' },
    });

    expect(deliveries).toHaveLength(0);
  });

  it('stamps the delivery payload with event metadata (id, type, created)', async () => {
    const { prisma, deliveries } = mkPrisma([
      { id: 'w1', orgId: 'org-1', url: 'https://a', events: ['job.completed'], secret: 's', active: true },
    ]);
    const queue = mkQueue();
    const dispatcher = createDispatcher({
      prisma: prisma as never,
      queue,
      logger: logger as never,
    });

    await dispatcher.dispatch({
      orgId: 'org-1',
      event: 'job.completed',
      payload: { jobId: 'job-42' },
    });

    const [row] = deliveries;
    expect(row.eventType).toBe('job.completed');
    expect(row.eventId).toMatch(/[0-9a-f-]+/);
    const payload = row.payload as { type: string; data: unknown; created: number };
    expect(payload.type).toBe('job.completed');
    expect(payload.data).toEqual({ jobId: 'job-42' });
    expect(typeof payload.created).toBe('number');
  });
});
