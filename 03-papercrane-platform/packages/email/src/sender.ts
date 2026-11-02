/**
 * Transactional email sender.
 *
 * Behavior:
 *   - In production with RESEND_API_KEY set and `opts.live=true`, dispatches
 *     via Resend's HTTP API. Tests/dev never hit the wire because both gates
 *     are required.
 *   - In dev (no RESEND_API_KEY, or opts.live=false): logs a structured JSON
 *     line and appends a record to .agent-logs/email-sent.log so engineers can
 *     observe the flow without Resend credentials.
 *   - Idempotency: callers pass `idempotencyKey` (typically the notification
 *     row's UUID). The sender keeps an in-memory LRU of recently seen keys so
 *     a worker retry doesn't double-send. The store is intentionally
 *     lightweight — for true cross-instance dedupe, the worker should rely on
 *     its database `notifications.email_sent_at` column.
 *
 * Plain-text fallback:
 *   We auto-derive a plain-text body from the rendered HTML using
 *   @react-email/render's `renderAsync(text: true)` flag. Email clients that
 *   request text/plain (mostly screen readers + terminal MUAs) get a clean
 *   fallback without us hand-writing one per template.
 */
import { promises as fs } from 'node:fs';
import path from 'node:path';
import * as React from 'react';
import { render } from '@react-email/render';
import { Resend } from 'resend';
import { z } from 'zod';

import { InviteEmail, inviteSubject, type InviteData } from './templates/Invite';
import {
  PasswordResetEmail,
  passwordResetSubject,
  type PasswordResetData,
} from './templates/PasswordReset';
import {
  JobCompleteEmail,
  jobCompleteSubject,
  type JobCompleteData,
} from './templates/JobComplete';
import {
  JobFailedEmail,
  jobFailedSubject,
  type JobFailedData,
} from './templates/JobFailed';
import {
  BillingReceiptEmail,
  billingReceiptSubject,
  type BillingReceiptData,
} from './templates/BillingReceipt';
import {
  WelcomeEmail,
  welcomeSubject,
  type WelcomeData,
} from './templates/WelcomeNewUser';

/* ------------------------------------------------------------------------ *
 * Types
 * ------------------------------------------------------------------------ */

export type TemplateName =
  | 'invite'
  | 'password-reset'
  | 'job-complete'
  | 'job-failed'
  | 'billing-receipt'
  | 'welcome';

export type TemplateDataMap = {
  invite: InviteData;
  'password-reset': PasswordResetData;
  'job-complete': JobCompleteData;
  'job-failed': JobFailedData;
  'billing-receipt': BillingReceiptData;
  welcome: WelcomeData;
};

export interface SendEmailInput<T extends TemplateName> {
  to: string;
  template: T;
  data: TemplateDataMap[T];
  /** Notification id or any unique key. Same key returns the cached result. */
  idempotencyKey?: string;
  /** Optional override for the From address. */
  from?: string;
  /** Optional override of the unsubscribe URL embedded in the layout. */
  unsubscribeUrl?: string;
}

export interface SendEmailResult {
  delivered: boolean;
  /** Resend message id (or empty string in dev). */
  providerMessageId: string;
  /** True when this dispatch was deduped against a prior identical key. */
  deduped: boolean;
  /** Mode used for this send. */
  mode: 'resend' | 'dev-log';
  /** The rendered subject line. */
  subject: string;
}

export interface SenderLogger {
  info: (obj: Record<string, unknown>, msg?: string) => void;
  warn: (obj: Record<string, unknown>, msg?: string) => void;
  error?: (obj: Record<string, unknown>, msg?: string) => void;
}

export interface SenderOptions {
  /**
   * If false (default in tests), no real Resend call is made even when
   * RESEND_API_KEY is present. We accept this flag explicitly so unit tests
   * can never accidentally hit the wire.
   */
  live?: boolean;
  /** Override the agent-logs path for tests. */
  devLogPath?: string;
  /** Logger to receive structured events. Defaults to console. */
  logger?: SenderLogger;
}

const inputSchema = z.object({
  to: z.string().email(),
  template: z.enum([
    'invite',
    'password-reset',
    'job-complete',
    'job-failed',
    'billing-receipt',
    'welcome',
  ]),
  idempotencyKey: z.string().min(1).optional(),
  from: z.string().email().optional(),
  unsubscribeUrl: z.string().url().optional(),
});

/* ------------------------------------------------------------------------ *
 * Idempotency LRU (in-memory; per-process)
 * ------------------------------------------------------------------------ */

const IDEMP_LRU_MAX = 1024;
const idempotencyCache = new Map<string, SendEmailResult>();

function cacheGet(key: string): SendEmailResult | undefined {
  const hit = idempotencyCache.get(key);
  if (!hit) return undefined;
  // refresh recency
  idempotencyCache.delete(key);
  idempotencyCache.set(key, hit);
  return { ...hit, deduped: true };
}

function cacheSet(key: string, value: SendEmailResult): void {
  if (idempotencyCache.size >= IDEMP_LRU_MAX) {
    const oldestKey = idempotencyCache.keys().next().value;
    if (oldestKey !== undefined) idempotencyCache.delete(oldestKey);
  }
  idempotencyCache.set(key, value);
}

/** Test-only: clears the dedupe cache. Not exported in the package barrel. */
export function __resetIdempotencyCacheForTests(): void {
  idempotencyCache.clear();
}

/* ------------------------------------------------------------------------ *
 * Render dispatch
 * ------------------------------------------------------------------------ */

interface Rendered {
  subject: string;
  html: string;
  text: string;
}

async function renderTemplate<T extends TemplateName>(
  template: T,
  data: TemplateDataMap[T],
): Promise<Rendered> {
  let element: React.ReactElement;
  let subject: string;

  switch (template) {
    case 'invite':
      element = InviteEmail(data as InviteData);
      subject = inviteSubject(data as InviteData);
      break;
    case 'password-reset':
      element = PasswordResetEmail(data as PasswordResetData);
      subject = passwordResetSubject(data as PasswordResetData);
      break;
    case 'job-complete':
      element = JobCompleteEmail(data as JobCompleteData);
      subject = jobCompleteSubject(data as JobCompleteData);
      break;
    case 'job-failed':
      element = JobFailedEmail(data as JobFailedData);
      subject = jobFailedSubject(data as JobFailedData);
      break;
    case 'billing-receipt':
      element = BillingReceiptEmail(data as BillingReceiptData);
      subject = billingReceiptSubject(data as BillingReceiptData);
      break;
    case 'welcome':
      element = WelcomeEmail(data as WelcomeData);
      subject = welcomeSubject(data as WelcomeData);
      break;
    default: {
      const _exhaust: never = template;
      throw new Error(`Unknown email template: ${String(_exhaust)}`);
    }
  }

  // react-email's render() is sync in v1; both the html + text variants are
  // produced by toggling the `plainText` flag.
  const html = await Promise.resolve(render(element));
  const text = await Promise.resolve(render(element, { plainText: true }));
  return { subject, html, text };
}

/* ------------------------------------------------------------------------ *
 * Public API
 * ------------------------------------------------------------------------ */

export async function sendEmail<T extends TemplateName>(
  input: SendEmailInput<T>,
  opts: SenderOptions = {},
): Promise<SendEmailResult> {
  // Validate the envelope; data is template-typed and trusted from the caller.
  inputSchema.parse({
    to: input.to,
    template: input.template,
    idempotencyKey: input.idempotencyKey,
    from: input.from,
    unsubscribeUrl: input.unsubscribeUrl,
  });

  const logger: SenderLogger = opts.logger ?? defaultConsoleLogger();

  // Idempotency short-circuit.
  if (input.idempotencyKey) {
    const cached = cacheGet(input.idempotencyKey);
    if (cached) {
      logger.info(
        { event: 'email.dedupe', key: input.idempotencyKey, template: input.template },
        'email skipped — duplicate idempotency key',
      );
      return cached;
    }
  }

  const apiKey = process.env.RESEND_API_KEY;
  const fromAddress =
    input.from ?? process.env.EMAIL_FROM_ADDRESS ?? 'Paper Crane <hello@papercrane.bio>';

  const rendered = await renderTemplate(input.template, input.data);

  let result: SendEmailResult;

  if (apiKey && opts.live === true) {
    const client = new Resend(apiKey);
    const provider = await client.emails.send({
      from: fromAddress,
      to: input.to,
      subject: rendered.subject,
      html: rendered.html,
      text: rendered.text,
    });
    if (provider.error) {
      throw new Error(`Resend send failed: ${provider.error.message}`);
    }
    if (!provider.data?.id) {
      throw new Error('Resend send failed: provider returned no message id');
    }
    result = {
      delivered: true,
      providerMessageId: provider.data.id,
      deduped: false,
      mode: 'resend',
      subject: rendered.subject,
    };
    logger.info(
      {
        event: 'email.live.queued',
        to: input.to,
        template: input.template,
        from: fromAddress,
        subject: rendered.subject,
      },
      'email accepted by Resend',
    );
  } else {
    // Dev mode: log + append to .agent-logs/email-sent.log
    const record = {
      ts: new Date().toISOString(),
      to: input.to,
      from: fromAddress,
      template: input.template,
      subject: rendered.subject,
      idempotencyKey: input.idempotencyKey ?? null,
      htmlBytes: rendered.html.length,
      textBytes: rendered.text.length,
    };
    logger.info({ event: 'email.dev.log', ...record }, 'email rendered (dev mode)');

    try {
      await appendDevLog(record, opts.devLogPath);
    } catch (err) {
      logger.warn(
        { event: 'email.dev.log.fail', error: (err as Error).message },
        'failed to append dev email log',
      );
    }

    result = {
      delivered: true,
      providerMessageId: '',
      deduped: false,
      mode: 'dev-log',
      subject: rendered.subject,
    };
  }

  if (input.idempotencyKey) {
    cacheSet(input.idempotencyKey, result);
  }

  return result;
}

/* ------------------------------------------------------------------------ *
 * Helpers
 * ------------------------------------------------------------------------ */

function defaultConsoleLogger(): SenderLogger {
  return {
    info: (obj, msg) => {
      // Compact JSON one-liner for grep-ability.
      // eslint-disable-next-line no-console
      console.log(JSON.stringify({ level: 'info', msg, ...obj }));
    },
    warn: (obj, msg) => {
      // eslint-disable-next-line no-console
      console.warn(JSON.stringify({ level: 'warn', msg, ...obj }));
    },
    error: (obj, msg) => {
      // eslint-disable-next-line no-console
      console.error(JSON.stringify({ level: 'error', msg, ...obj }));
    },
  };
}

async function appendDevLog(
  record: Record<string, unknown>,
  override?: string,
): Promise<void> {
  // Resolve to repo root .agent-logs/email-sent.log unless overridden.
  // We walk up from cwd looking for the .agent-logs dir; if absent, we
  // fall back to creating it under cwd.
  const logPath = override ?? (await resolveDefaultDevLogPath());
  await fs.mkdir(path.dirname(logPath), { recursive: true });
  await fs.appendFile(logPath, `${JSON.stringify(record)}\n`, 'utf8');
}

async function resolveDefaultDevLogPath(): Promise<string> {
  // Walk up at most 6 levels looking for an existing .agent-logs.
  let dir = process.cwd();
  for (let i = 0; i < 6; i++) {
    const candidate = path.join(dir, '.agent-logs');
    try {
      const stat = await fs.stat(candidate);
      if (stat.isDirectory()) return path.join(candidate, 'email-sent.log');
    } catch {
      // not found at this level
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return path.join(process.cwd(), '.agent-logs', 'email-sent.log');
}
