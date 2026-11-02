/**
 * Invite-email service (stub).
 *
 * Today this function emits a structured JSON line to the provided logger so
 * local dev and CI can observe invite flow without a real SMTP/provider
 * connection. In follow-up work we wire this to Resend (or Postmark) behind
 * the same signature — callers do not need to change.
 *
 * Keeping the service HTTP-agnostic means the tRPC router (and any future
 * background job) can call it directly without dragging Fastify in.
 *
 * Security notes:
 *   - Never log the full `token` at info level in production. We log a
 *     fingerprint (first 8 chars) so operators can correlate with the DB row
 *     without the log line becoming a credential itself.
 *   - The `acceptUrl` is constructed from the provided `appBaseUrl`; the
 *     caller is responsible for validating/trusting that base URL.
 */
import { z } from "zod";

/** Minimum logger shape we need; compatible with Fastify / Pino / console. */
export interface InviteLogger {
  info: (obj: Record<string, unknown>, msg?: string) => void;
  warn: (obj: Record<string, unknown>, msg?: string) => void;
}

export const SendInviteEmailInputSchema = z
  .object({
    to: z.string().email(),
    token: z.string().min(16),
    orgName: z.string().min(1).max(200),
    invitedBy: z.string().min(1).max(200),
    role: z.enum(["viewer", "member", "admin", "owner"]),
    /** e.g. `https://app.papercrane.bio`. No trailing slash. */
    appBaseUrl: z.string().url(),
  })
  .strict();

export type SendInviteEmailInput = z.infer<typeof SendInviteEmailInputSchema>;

export interface SendInviteEmailResult {
  /** True iff the stub logged/emitted successfully. */
  delivered: boolean;
  /** Provider-assigned id (empty while we're still a stub). */
  providerMessageId: string;
  /** The fully-rendered accept URL that the email links to. */
  acceptUrl: string;
  /** Fingerprint (first 8 chars of the token) — safe to log. */
  tokenFingerprint: string;
}

/**
 * Build the `/invite/:token` URL that the email links to. Exported so the
 * router can reuse the exact same formatter when pre-computing response
 * payloads (e.g. for "copy invite link" UI).
 */
export function buildAcceptUrl(appBaseUrl: string, token: string): string {
  const trimmed = appBaseUrl.replace(/\/+$/, "");
  return `${trimmed}/invite/${encodeURIComponent(token)}`;
}

/**
 * "Send" an invite email. For now this logs a structured JSON record; a
 * follow-up PR will swap the implementation body for a Resend/Postmark call
 * while keeping this function signature stable.
 *
 * The caller supplies a logger so tests can inspect the emitted payload
 * without touching the real Pino instance.
 */
export async function sendInviteEmail(
  input: SendInviteEmailInput,
  opts: { logger: InviteLogger },
): Promise<SendInviteEmailResult> {
  const parsed = SendInviteEmailInputSchema.parse(input);
  const { to, token, orgName, invitedBy, role, appBaseUrl } = parsed;

  const acceptUrl = buildAcceptUrl(appBaseUrl, token);
  const tokenFingerprint = token.slice(0, 8);

  opts.logger.info(
    {
      event: "invite.email.stub",
      to,
      orgName,
      invitedBy,
      role,
      acceptUrl,
      tokenFingerprint,
    },
    "invite email (stub) dispatched",
  );

  return {
    delivered: true,
    providerMessageId: "",
    acceptUrl,
    tokenFingerprint,
  };
}
