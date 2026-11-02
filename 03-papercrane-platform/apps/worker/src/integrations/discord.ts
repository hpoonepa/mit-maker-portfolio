/**
 * Discord incoming-webhook poster (Wave 14).
 *
 * Discord webhooks render JSON as a single message with up to 10 "embeds".
 * Each embed has a coloured side-bar, title (with optional URL), description,
 * and an array of fields (label/value pairs). We use one embed per event.
 *
 * The colour bar is keyed off event severity:
 *   green     job.completed, billing.upgraded, design.created
 *   amber     usage.cap_warning, member.invited
 *   red       job.failed, usage.cap_reached
 *   neutral   system.test (and any unknown event)
 *
 * Discord docs: https://discord.com/developers/docs/resources/webhook
 *
 * As with Slack: pure formatter + thin POST helper. No retry logic — the
 * router decides whether to re-enqueue.
 */

import type { IntegrationEvent, IntegrationDeliveryResult } from './router';

// ─── Embed shapes ───────────────────────────────────────────────────────────

interface DiscordEmbed {
  title: string;
  description?: string;
  url?: string;
  /** Decimal RGB integer; Discord parses it as 0xRRGGBB. */
  color: number;
  fields?: Array<{ name: string; value: string; inline?: boolean }>;
  footer?: { text: string };
  timestamp?: string;
}

export interface DiscordMessage {
  /** Plaintext content shown above embeds. We leave it empty by default. */
  content?: string;
  embeds: DiscordEmbed[];
  /** Branding override for the message. */
  username?: string;
}

// ─── Colours ────────────────────────────────────────────────────────────────

const COLOR_GREEN = 0x2ecc71;
const COLOR_AMBER = 0xf1c40f;
const COLOR_RED = 0xe74c3c;
const COLOR_NEUTRAL = 0x95a5a6;

function colorFor(eventType: string): number {
  switch (eventType) {
    case 'job.completed':
    case 'billing.upgraded':
    case 'design.created':
      return COLOR_GREEN;
    case 'usage.cap_warning':
    case 'member.invited':
      return COLOR_AMBER;
    case 'job.failed':
    case 'usage.cap_reached':
      return COLOR_RED;
    default:
      return COLOR_NEUTRAL;
  }
}

// ─── Formatter ──────────────────────────────────────────────────────────────

export function formatDiscordMessage(event: IntegrationEvent): DiscordMessage {
  const title = titleFor(event);
  const url = event.actionUrl ?? defaultAppUrl();
  const color = colorFor(event.type);
  const fields = fieldsFor(event);

  const embed: DiscordEmbed = {
    title: title.slice(0, 256), // Discord caps embed titles at 256 chars
    description: descriptionFor(event)?.slice(0, 4096),
    url,
    color,
    fields: fields.length > 0 ? fields : undefined,
    footer: { text: 'Paper Crane' },
    timestamp: new Date(event.timestamp ?? Date.now()).toISOString(),
  };

  return {
    embeds: [embed],
    username: 'Paper Crane',
  };
}

// ─── Poster ─────────────────────────────────────────────────────────────────

export interface DiscordPosterDeps {
  fetch?: typeof fetch;
}

export async function postDiscordMessage(
  webhookUrl: string,
  message: DiscordMessage,
  deps: DiscordPosterDeps = {},
): Promise<IntegrationDeliveryResult> {
  const f = deps.fetch ?? fetch;
  try {
    // Discord supports `?wait=true` to make the webhook return the resulting
    // message, but it adds latency and we don't need the response body.
    const res = await f(webhookUrl, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(message),
    });
    const ok = res.status >= 200 && res.status < 300;
    return {
      ok,
      statusCode: res.status,
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

function titleFor(event: IntegrationEvent): string {
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
      return `Invited ${event.payload.email ?? 'a teammate'}`;
    case 'usage.cap_warning':
      return `Usage at ${event.payload.percent ?? 80}% of monthly cap`;
    case 'usage.cap_reached':
      return 'Monthly seed cap reached';
    case 'system.test':
      return 'Test message from Paper Crane';
    default:
      return event.payload.title ?? `Paper Crane event: ${event.type}`;
  }
}

function descriptionFor(event: IntegrationEvent): string | undefined {
  if (event.payload.description) return String(event.payload.description);
  if (event.type === 'usage.cap_reached') {
    return 'New jobs will be blocked until the next billing cycle or an upgrade.';
  }
  if (event.type === 'system.test') {
    return 'If you can read this, your Discord integration is wired up correctly.';
  }
  return undefined;
}

function fieldsFor(event: IntegrationEvent): Array<{ name: string; value: string; inline: boolean }> {
  const p = event.payload;
  const out: Array<{ name: string; value: string; inline: boolean }> = [];
  if (p.project) out.push({ name: 'Project', value: String(p.project), inline: true });
  if (p.tool) out.push({ name: 'Tool', value: String(p.tool), inline: true });
  if (typeof p.designs === 'number')
    out.push({ name: 'Designs', value: String(p.designs), inline: true });
  if (typeof p.topIptm === 'number')
    out.push({ name: 'Top ipTM', value: p.topIptm.toFixed(2), inline: true });
  if (p.error) {
    out.push({
      name: 'Error',
      value: `\`\`\`${String(p.error).slice(0, 1000)}\`\`\``,
      inline: false,
    });
  }
  return out;
}

function defaultAppUrl(): string {
  return process.env.PAPERCRANE_APP_URL ?? 'https://app.papercrane.bio';
}

async function safeText(res: Response): Promise<string> {
  try {
    return (await res.text()).slice(0, 500);
  } catch {
    return '';
  }
}
