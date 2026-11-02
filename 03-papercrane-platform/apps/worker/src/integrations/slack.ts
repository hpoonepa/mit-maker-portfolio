/**
 * Slack incoming-webhook poster (Wave 14).
 *
 * Formats one of our domain events as a Slack Block Kit message and POSTs
 * it to the org's incoming-webhook URL. We intentionally use Block Kit
 * (not plaintext) so messages render with structure on every Slack client,
 * including mobile and the desktop reduced-width layout.
 *
 * Block layout:
 *   1. `section` with the headline (mrkdwn — `*bold*`, `<url|text>` etc.).
 *   2. optional `section` with a fields grid (project, tool, top metric).
 *   3. `actions` row with a single "View in Paper Crane" link button.
 *   4. `context` row with a small footer ("Paper Crane · 2:14pm UTC").
 *
 * Block Kit reference: https://api.slack.com/block-kit
 *
 * Network policy
 *   In dev (no real Slack URL) the worker passes a localhost echo URL so
 *   integration tests can assert on the JSON body without leaving the
 *   machine. The poster doesn't care — it just POSTs and trusts the URL
 *   from the DB.
 */

import type { IntegrationEvent, IntegrationDeliveryResult } from './router';

// ─── Block builders ─────────────────────────────────────────────────────────

interface SectionBlock {
  type: 'section';
  text: { type: 'mrkdwn'; text: string };
  fields?: Array<{ type: 'mrkdwn'; text: string }>;
}

interface ActionsBlock {
  type: 'actions';
  elements: Array<{
    type: 'button';
    text: { type: 'plain_text'; text: string };
    url: string;
    style?: 'primary' | 'danger';
  }>;
}

interface ContextBlock {
  type: 'context';
  elements: Array<{ type: 'mrkdwn'; text: string }>;
}

type SlackBlock = SectionBlock | ActionsBlock | ContextBlock;

export interface SlackMessage {
  blocks: SlackBlock[];
  /** Plaintext fallback for notifications/unfurls. */
  text: string;
}

// ─── Formatter ──────────────────────────────────────────────────────────────

/**
 * Build the Slack Block Kit body for a domain event. Pure — no I/O. The
 * router calls this and either passes the result to `postSlackMessage`
 * (production) or asserts on it directly (tests).
 */
export function formatSlackMessage(event: IntegrationEvent): SlackMessage {
  const headline = headlineFor(event);
  const viewUrl = event.actionUrl ?? defaultAppUrl();

  const blocks: SlackBlock[] = [
    {
      type: 'section',
      text: { type: 'mrkdwn', text: `*${escapeMrkdwn(headline)}*` },
    },
  ];

  const fields = fieldsFor(event);
  if (fields.length > 0) {
    blocks.push({
      type: 'section',
      text: { type: 'mrkdwn', text: ' ' }, // Slack requires text on a section
      fields: fields.map((f) => ({
        type: 'mrkdwn',
        text: `*${escapeMrkdwn(f.label)}*\n${escapeMrkdwn(f.value)}`,
      })),
    });
  }

  blocks.push({
    type: 'actions',
    elements: [
      {
        type: 'button',
        text: { type: 'plain_text', text: 'View in Paper Crane' },
        url: viewUrl,
      },
    ],
  });

  blocks.push({
    type: 'context',
    elements: [
      {
        type: 'mrkdwn',
        text: `Paper Crane · ${formatTimestamp(event.timestamp ?? Date.now())}`,
      },
    ],
  });

  return { blocks, text: headline };
}

// ─── Poster ─────────────────────────────────────────────────────────────────

export interface SlackPosterDeps {
  /** Injected for tests. Defaults to global fetch. */
  fetch?: typeof fetch;
}

/**
 * POST a formatted message to a Slack incoming webhook URL. Returns the
 * delivery outcome the router needs to update the channel row. Treats any
 * non-2xx as a failure but does NOT throw — the router decides retry policy.
 */
export async function postSlackMessage(
  webhookUrl: string,
  message: SlackMessage,
  deps: SlackPosterDeps = {},
): Promise<IntegrationDeliveryResult> {
  const f = deps.fetch ?? fetch;
  try {
    const res = await f(webhookUrl, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(message),
    });
    const ok = res.status >= 200 && res.status < 300;
    return {
      ok,
      statusCode: res.status,
      // Slack returns the literal string "ok" on success, or an error code.
      body: await safeText(res),
    };
  } catch (err) {
    return {
      ok: false,
      statusCode: null,
      body: err instanceof Error ? err.message : String(err),
    };
  }
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function headlineFor(event: IntegrationEvent): string {
  switch (event.type) {
    case 'job.completed':
      return `Job complete: ${event.payload.title ?? 'Untitled job'}`;
    case 'job.failed':
      return `Job failed: ${event.payload.title ?? 'Untitled job'}`;
    case 'design.created':
      return `New design: ${event.payload.title ?? 'Untitled design'}`;
    case 'billing.upgraded':
      return `Plan upgraded to ${event.payload.tier ?? 'pro'}`;
    case 'member.invited':
      return `Invited ${event.payload.email ?? 'a teammate'} to the workspace`;
    case 'usage.cap_warning':
      return `Usage at ${event.payload.percent ?? 80}% of monthly seed cap`;
    case 'usage.cap_reached':
      return 'Monthly seed cap reached — new jobs will require an upgrade';
    case 'system.test':
      return 'Test message from Paper Crane';
    default:
      return event.payload.title ?? `Paper Crane event: ${event.type}`;
  }
}

interface Field {
  label: string;
  value: string;
}

function fieldsFor(event: IntegrationEvent): Field[] {
  const out: Field[] = [];
  const p = event.payload;
  if (p.project) out.push({ label: 'Project', value: String(p.project) });
  if (p.tool) out.push({ label: 'Tool', value: String(p.tool) });
  if (typeof p.designs === 'number') out.push({ label: 'Designs', value: String(p.designs) });
  if (typeof p.topIptm === 'number')
    out.push({ label: 'Top ipTM', value: p.topIptm.toFixed(2) });
  if (p.error) out.push({ label: 'Error', value: String(p.error).slice(0, 200) });
  return out;
}

/**
 * Slack mrkdwn special characters: `&`, `<`, `>`. Block Kit auto-handles
 * the rest. We escape only these three to keep formatting characters
 * (`*`, `_`) usable inside the headline.
 */
function escapeMrkdwn(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function defaultAppUrl(): string {
  return process.env.PAPERCRANE_APP_URL ?? 'https://app.papercrane.bio';
}

function formatTimestamp(ms: number): string {
  const d = new Date(ms);
  // Stable UTC short format, no locale variance.
  const hh = d.getUTCHours().toString().padStart(2, '0');
  const mm = d.getUTCMinutes().toString().padStart(2, '0');
  return `${hh}:${mm} UTC`;
}

async function safeText(res: Response): Promise<string> {
  try {
    return (await res.text()).slice(0, 500);
  } catch {
    return '';
  }
}
