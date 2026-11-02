/**
 * Notification → email processor.
 *
 * Listens (via the worker's BullMQ wiring) for `notification.created` events
 * and dispatches the matching transactional template through @papercrane/email.
 *
 * Routing rules (category → template):
 *   - invite        → 'invite'
 *   - job (success) → 'job-complete'
 *   - job (failure) → 'job-failed'
 *   - billing       → 'billing-receipt'
 *   - system (welcome) → 'welcome'
 *   - webhook       → no email (in-app only)
 *
 * Inputs are deliberately kept narrow — we accept the notification row plus
 * a hydrated payload built upstream (the API/worker already knows the
 * project, tool chain, top design, etc. when the notification was created
 * and stuffs it into `metadata`).
 *
 * Idempotency: the notification's primary key is forwarded as the
 * `idempotencyKey`, so a BullMQ retry of the same job will dedupe inside the
 * sender's LRU rather than double-emailing. For cross-instance dedupe the
 * worker should additionally check `notification.email_sent_at` (added in a
 * future migration) before invoking this processor.
 *
 * Pure-function shape: deps are passed in (logger, sendEmail) so unit tests
 * can stub @papercrane/email entirely.
 */
import { z } from 'zod';
import {
  sendEmail as defaultSendEmail,
  type SendEmailInput,
  type SendEmailResult,
  type SenderLogger,
  type TemplateName,
} from '@papercrane/email';

/* ------------------------------------------------------------------------ *
 * Types
 * ------------------------------------------------------------------------ */

export type NotificationCategory =
  | 'job'
  | 'billing'
  | 'webhook'
  | 'invite'
  | 'system';

export interface NotificationRow {
  id: string;
  orgId: string;
  userId: string;
  category: NotificationCategory;
  title: string;
  description?: string | null;
  actionUrl?: string | null;
  /** Free-form payload — the upstream creator stuffs template-specific fields here. */
  metadata: Record<string, unknown>;
}

export interface NotificationProcessorInput {
  notification: NotificationRow;
  /** Recipient address — pulled by the caller from the user record. */
  recipientEmail: string;
  /** Recipient display name; passed through to templates that show it. */
  recipientName?: string;
}

export interface NotificationProcessorDeps {
  logger: SenderLogger;
  /** Override the sender for tests. */
  sendEmail?: typeof defaultSendEmail;
  /** Skip the email entirely (e.g. user has email channel muted). */
  skip?: boolean;
}

export type NotificationProcessorResult =
  | { dispatched: false; reason: string }
  | { dispatched: true; result: SendEmailResult };

/* ------------------------------------------------------------------------ *
 * Metadata schemas — one per template the notification might map to.
 * Kept loose (passthrough) so upstream can add fields without breaking us;
 * the required fields are enforced strictly.
 * ------------------------------------------------------------------------ */

const inviteMetaSchema = z
  .object({
    inviterName: z.string().min(1),
    orgName: z.string().min(1),
    role: z.enum(['viewer', 'member', 'admin', 'owner']),
    acceptUrl: z.string().url(),
    expiresInHours: z.number().int().positive().optional(),
  })
  .passthrough();

const jobCompleteMetaSchema = z
  .object({
    toolChain: z.string().min(1),
    projectName: z.string().min(1),
    designCount: z.number().int().nonnegative(),
    runtime: z.string().min(1),
    jobUrl: z.string().url(),
    designsUrl: z.string().url(),
    topThumbnailUrl: z.string().url().optional(),
    topMetric: z.string().optional(),
    /** Discriminator for category=job → success vs failure. */
    outcome: z.literal('succeeded').optional(),
  })
  .passthrough();

const jobFailedMetaSchema = z
  .object({
    toolChain: z.string().min(1),
    projectName: z.string().min(1),
    errorHeadline: z.string().min(1),
    errorDetail: z.string().optional(),
    retryUrl: z.string().url(),
    jobUrl: z.string().url(),
    outcome: z.literal('failed'),
  })
  .passthrough();

const billingMetaSchema = z
  .object({
    periodLabel: z.string().min(1),
    orgName: z.string().min(1),
    invoiceUrl: z.string().url(),
    invoicePdfUrl: z.string().url().optional(),
    lineItems: z
      .array(z.object({ label: z.string(), amountUsd: z.number() }))
      .min(1),
    totalUsd: z.number(),
    cardLast4: z.string().length(4).optional(),
  })
  .passthrough();

const welcomeMetaSchema = z
  .object({
    quickstartUrl: z.string().url(),
    docsUrl: z.string().url().optional(),
    /** Discriminator for category=system → welcome vs other system messages. */
    kind: z.literal('welcome'),
  })
  .passthrough();

/* ------------------------------------------------------------------------ *
 * Routing
 * ------------------------------------------------------------------------ */

/**
 * Decide which template (if any) maps to a given notification. Returns
 * `null` for categories that intentionally have no email counterpart.
 */
export function resolveTemplate(n: NotificationRow): TemplateName | null {
  switch (n.category) {
    case 'invite':
      return 'invite';
    case 'billing':
      return 'billing-receipt';
    case 'job': {
      const outcome = (n.metadata as { outcome?: unknown }).outcome;
      return outcome === 'failed' ? 'job-failed' : 'job-complete';
    }
    case 'system': {
      const kind = (n.metadata as { kind?: unknown }).kind;
      return kind === 'welcome' ? 'welcome' : null;
    }
    case 'webhook':
      return null;
    default: {
      // Exhaustiveness check — flags new enum values at compile time.
      const _exhaust: never = n.category;
      return _exhaust;
    }
  }
}

/* ------------------------------------------------------------------------ *
 * Main processor
 * ------------------------------------------------------------------------ */

export async function processNotificationEmail(
  input: NotificationProcessorInput,
  deps: NotificationProcessorDeps,
): Promise<NotificationProcessorResult> {
  const { notification, recipientEmail, recipientName } = input;
  const send = deps.sendEmail ?? defaultSendEmail;
  const log = deps.logger;

  if (deps.skip) {
    log.info(
      {
        event: 'notification.email.skip',
        notificationId: notification.id,
        reason: 'preferences-muted',
      },
      'email skipped — user muted this category',
    );
    return { dispatched: false, reason: 'preferences-muted' };
  }

  const template = resolveTemplate(notification);
  if (!template) {
    log.info(
      {
        event: 'notification.email.skip',
        notificationId: notification.id,
        category: notification.category,
        reason: 'no-template',
      },
      'no email template for this notification category',
    );
    return { dispatched: false, reason: 'no-template' };
  }

  const meta = notification.metadata ?? {};
  const idempotencyKey = notification.id;

  let payload: SendEmailInput<TemplateName>;
  try {
    payload = buildPayload(template, meta, {
      to: recipientEmail,
      recipientName,
      idempotencyKey,
    });
  } catch (err) {
    log.warn(
      {
        event: 'notification.email.invalid_metadata',
        notificationId: notification.id,
        template,
        error: (err as Error).message,
      },
      'notification metadata failed schema validation; not sending',
    );
    return { dispatched: false, reason: 'invalid-metadata' };
  }

  const result = await send(payload, { logger: log });
  log.info(
    {
      event: 'notification.email.sent',
      notificationId: notification.id,
      template,
      mode: result.mode,
      deduped: result.deduped,
    },
    'notification email dispatched',
  );
  return { dispatched: true, result };
}

/* ------------------------------------------------------------------------ *
 * Payload builders
 * ------------------------------------------------------------------------ */

interface BuildArgs {
  to: string;
  recipientName?: string;
  idempotencyKey: string;
}

function buildPayload(
  template: TemplateName,
  meta: Record<string, unknown>,
  args: BuildArgs,
): SendEmailInput<TemplateName> {
  const base = {
    to: args.to,
    idempotencyKey: args.idempotencyKey,
  };

  switch (template) {
    case 'invite': {
      const data = inviteMetaSchema.parse(meta);
      return { ...base, template, data } as SendEmailInput<'invite'>;
    }
    case 'job-complete': {
      const data = jobCompleteMetaSchema.parse(meta);
      return { ...base, template, data } as SendEmailInput<'job-complete'>;
    }
    case 'job-failed': {
      const data = jobFailedMetaSchema.parse(meta);
      return { ...base, template, data } as SendEmailInput<'job-failed'>;
    }
    case 'billing-receipt': {
      const data = billingMetaSchema.parse(meta);
      return { ...base, template, data } as SendEmailInput<'billing-receipt'>;
    }
    case 'welcome': {
      const data = welcomeMetaSchema.parse(meta);
      return {
        ...base,
        template,
        data: { ...data, userName: args.recipientName },
      } as SendEmailInput<'welcome'>;
    }
    case 'password-reset': {
      // Password reset is initiated by the auth flow directly — never via a
      // notification row. We keep the case for type exhaustiveness.
      throw new Error('password-reset is dispatched directly, not via notifications');
    }
    default: {
      const _exhaust: never = template;
      throw new Error(`Unhandled template: ${String(_exhaust)}`);
    }
  }
}
