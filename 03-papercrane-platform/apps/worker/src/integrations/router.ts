/**
 * Integration router (Wave 14) — fan an internal domain event out to every
 * connected Slack/Discord channel that opted into it.
 *
 * Wire-up
 *   The worker listens for `notification.created` (and a few synthetic
 *   "system" events the API can fire directly) and calls `dispatch()` here.
 *   We DO NOT reuse the public `webhooks` event registry — that one is
 *   smaller and stricter (only the canonical job/design events). Chat
 *   integrations want billing + member + usage events too.
 *
 * Flow per event:
 *   1. Find every (integration, channel) pair where:
 *        - org_id matches
 *        - muted = false
 *        - events @> [eventType]
 *   2. Format the event for the integration's `kind` (slack | discord).
 *   3. POST. Update the channel row with delivery metadata.
 *   4. Per-channel failures are logged; one failure does not poison siblings.
 *
 * Test discipline
 *   We don't have real Slack/Discord webhook URLs in dev. Tests inject a
 *   `fetch` stub that records the request and returns a synthetic response.
 *   The localhost echo recipe lives in the README — POST to
 *   `http://localhost:9999/echo` and the dev fixture echoes the body back.
 */

import type { PrismaClient } from '@papercrane/db';
import type { Logger } from '@papercrane/observability';
import { formatSlackMessage, postSlackMessage } from './slack';
import { formatDiscordMessage, postDiscordMessage } from './discord';

// ─── Event registry ─────────────────────────────────────────────────────────
// Mirror of `INTEGRATION_EVENTS` in `packages/trpc/src/routers/integrations.ts`.
// Duplicated rather than cross-imported to avoid the worker depending on the
// tRPC package (keeps the worker bundle lean).

export type IntegrationEventName =
  | 'job.completed'
  | 'job.failed'
  | 'design.created'
  | 'billing.upgraded'
  | 'member.invited'
  | 'usage.cap_warning'
  | 'usage.cap_reached'
  | 'system.test';

export interface IntegrationEventPayload {
  /** Short headline used as the message title. */
  title?: string;
  /** Optional longer body — only used by Discord embeds today. */
  description?: string;
  // Common metric fields the formatters know how to render:
  project?: string;
  tool?: string;
  designs?: number;
  topIptm?: number;
  error?: string;
  tier?: 'pro' | 'frontier';
  email?: string;
  percent?: number;
  // Future-proof escape hatch.
  [key: string]: unknown;
}

export interface IntegrationEvent {
  orgId: string;
  type: IntegrationEventName;
  payload: IntegrationEventPayload;
  /** Deep link to surface in the message ("View in Paper Crane"). */
  actionUrl?: string;
  /** ms epoch of when the underlying event happened. Defaults to now. */
  timestamp?: number;
}

export interface IntegrationDeliveryResult {
  ok: boolean;
  statusCode: number | null;
  body?: string;
}

// ─── Router ─────────────────────────────────────────────────────────────────

export interface IntegrationRouterDeps {
  prisma: PrismaClient;
  logger: Logger;
  /** Injected for tests; defaults to global fetch in each poster. */
  fetch?: typeof fetch;
}

export interface IntegrationRouter {
  dispatch(event: IntegrationEvent): Promise<{ delivered: number; failed: number }>;
}

interface ChannelRow {
  id: string;
  webhookUrl: string;
  events: string[];
  muted: boolean;
  capWarningPct: number;
  integration: { kind: 'slack' | 'discord' };
}

export function createIntegrationRouter(deps: IntegrationRouterDeps): IntegrationRouter {
  const { prisma, logger, fetch: fetchImpl } = deps;

  return {
    async dispatch(event: IntegrationEvent): Promise<{ delivered: number; failed: number }> {
      // ---- 1. Find every channel subscribed to this event ----
      // We cast through `any` because Prisma's generated types depend on the
      // `Integration` model which is added in the same wave migration; this
      // keeps the worker building before `prisma generate` runs.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const channels = (await (prisma as any).integrationChannel.findMany({
        where: {
          muted: false,
          events: { has: event.type },
          integration: { orgId: event.orgId },
        },
        include: { integration: true },
      })) as ChannelRow[];

      if (channels.length === 0) {
        logger.debug(
          { orgId: event.orgId, type: event.type },
          'integrations: no subscribers',
        );
        return { delivered: 0, failed: 0 };
      }

      // ---- 2. Special case: usage.cap_warning threshold filter ----
      // Each channel can set its own warning threshold (default 80%). Skip
      // channels whose threshold isn't met yet.
      const filtered = channels.filter((c) => {
        if (event.type !== 'usage.cap_warning') return true;
        const pct = typeof event.payload.percent === 'number' ? event.payload.percent : 0;
        return pct >= c.capWarningPct;
      });

      // ---- 3. Format + POST per channel ----
      let delivered = 0;
      let failed = 0;
      for (const ch of filtered) {
        try {
          const result = await postOne(ch, event, fetchImpl);
          if (result.ok) {
            delivered += 1;
          } else {
            failed += 1;
            logger.warn(
              { channelId: ch.id, kind: ch.integration.kind, statusCode: result.statusCode },
              'integrations: non-2xx response',
            );
          }
          // ---- 4. Update channel delivery metadata ----
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          await (prisma as any).integrationChannel.update({
            where: { id: ch.id },
            data: {
              lastDeliveredAt: new Date(),
              lastStatusCode: result.statusCode,
              failureCount: result.ok ? 0 : { increment: 1 },
            },
          });
        } catch (err) {
          failed += 1;
          logger.error(
            { err, channelId: ch.id, kind: ch.integration.kind },
            'integrations: dispatch failed',
          );
        }
      }

      logger.info(
        {
          orgId: event.orgId,
          type: event.type,
          subscribers: filtered.length,
          delivered,
          failed,
        },
        'integrations: fan-out',
      );
      return { delivered, failed };
    },
  };
}

async function postOne(
  channel: ChannelRow,
  event: IntegrationEvent,
  fetchImpl: typeof fetch | undefined,
): Promise<IntegrationDeliveryResult> {
  if (channel.integration.kind === 'slack') {
    const message = formatSlackMessage(event);
    return postSlackMessage(channel.webhookUrl, message, { fetch: fetchImpl });
  }
  const message = formatDiscordMessage(event);
  return postDiscordMessage(channel.webhookUrl, message, { fetch: fetchImpl });
}

// ─── Notification → integration adapter ─────────────────────────────────────
// The worker listens for `notification.created` events emitted by the
// notifications service and translates them into integration events. This
// keeps the producer side simple (worker code only fires *one* internal
// event per state change) while letting the integration registry have a
// richer event vocabulary.

export function notificationToIntegrationEvent(notification: {
  orgId: string;
  category: 'job' | 'billing' | 'webhook' | 'invite' | 'system';
  title: string;
  description: string | null;
  actionUrl: string | null;
  metadata: Record<string, unknown>;
}): IntegrationEvent | null {
  const md = notification.metadata ?? {};
  const subtype = typeof md['subtype'] === 'string' ? (md['subtype'] as string) : null;

  // Map (category, subtype) → integration event name.
  let type: IntegrationEventName | null = null;
  if (notification.category === 'job') {
    if (subtype === 'completed' || subtype === 'succeeded') type = 'job.completed';
    else if (subtype === 'failed' || subtype === 'cancelled') type = 'job.failed';
  } else if (notification.category === 'billing') {
    if (subtype === 'upgraded') type = 'billing.upgraded';
    else if (subtype === 'cap_warning') type = 'usage.cap_warning';
    else if (subtype === 'cap_reached') type = 'usage.cap_reached';
  } else if (notification.category === 'invite') {
    type = 'member.invited';
  }

  if (!type) return null;

  return {
    orgId: notification.orgId,
    type,
    payload: {
      title: notification.title,
      description: notification.description ?? undefined,
      ...md,
    },
    actionUrl: notification.actionUrl ?? undefined,
    timestamp: Date.now(),
  };
}
