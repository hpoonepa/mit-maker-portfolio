/**
 * Dispatcher — fan out one domain event to N subscribed webhooks.
 *
 * Called by the job processor (and any future producer) whenever an event
 * fires. Flow:
 *   1. Find every `webhook` row where `orgId == event.orgId`, `active == true`,
 *      and `events` contains the event name.
 *   2. For each match, create a `webhookDelivery` row (attempt = 1) with the
 *      full payload envelope. The row is durable — even if Redis drops the
 *      BullMQ job, a future sweeper can re-enqueue from the DB.
 *   3. Enqueue one BullMQ job per delivery. The processor is responsible for
 *      the actual HTTPS POST + retry scheduling.
 *
 * All DB writes happen sequentially (not in a single tx) because each
 * delivery is independent — a partial failure leaves some deliveries
 * enqueued, which is fine.
 */

import crypto from 'node:crypto';
import type { PrismaClient } from '@papercrane/db';
import type { Logger } from '@papercrane/observability';
import type { DomainEvent, WebhookEventName, WebhookPayload, WebhookQueue } from './types';
import { enqueueWebhookDelivery } from './queue';

export interface DispatcherDeps {
  prisma: PrismaClient;
  queue: WebhookQueue;
  logger: Logger;
}

export interface Dispatcher {
  dispatch<T = unknown>(event: DomainEvent<T>): Promise<{ delivered: number }>;
}

export function createDispatcher(deps: DispatcherDeps): Dispatcher {
  const { prisma, queue, logger } = deps;

  return {
    async dispatch<T>(domainEvent: DomainEvent<T>): Promise<{ delivered: number }> {
      const { orgId, event, payload } = domainEvent;

      // ---- 1. Find subscribed webhooks ----
      // `events` is a Postgres text[] in the schema → Prisma exposes the
      // `has` filter. Cast because the Prisma client types flex per-model
      // and we don't want to import the narrow generated type here.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const webhooks = await (prisma as any).webhook.findMany({
        where: { orgId, active: true, events: { has: event } },
      });

      if (webhooks.length === 0) {
        logger.debug({ orgId, event }, 'dispatcher: no subscribers');
        return { delivered: 0 };
      }

      // ---- 2 + 3. Per-webhook: create row + enqueue ----
      const eventId = crypto.randomUUID();
      const created = Math.floor(Date.now() / 1000);

      let delivered = 0;
      for (const webhook of webhooks as Array<{ id: string }>) {
        try {
          const envelope: WebhookPayload<T> = {
            id: eventId,
            created,
            type: event as WebhookEventName,
            data: payload,
          };

          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const row = await (prisma as any).webhookDelivery.create({
            data: {
              webhookId: webhook.id,
              eventId,
              eventType: event,
              payload: envelope as unknown,
              attempt: 1,
            },
          });

          await enqueueWebhookDelivery(queue, { deliveryId: row.id, attempt: 1 });
          delivered += 1;
        } catch (err) {
          // One webhook failing to enqueue shouldn't poison the others.
          logger.error(
            { err, webhookId: webhook.id, orgId, event },
            'dispatcher: failed to create/enqueue delivery',
          );
        }
      }

      logger.info({ orgId, event, subscribers: webhooks.length, delivered }, 'dispatcher: fan-out');
      return { delivered };
    },
  };
}
