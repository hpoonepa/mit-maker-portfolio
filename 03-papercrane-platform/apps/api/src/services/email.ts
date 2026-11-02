/**
 * Email service — thin wrapper around @papercrane/email/sendEmail that
 * threads the per-request Fastify logger and resolves the live/dev mode
 * from process env exactly once.
 *
 * Callers should prefer this wrapper over importing `sendEmail` directly so
 * we have one place to add tracing, rate limiting, or error normalization.
 *
 * Design notes:
 *   - The wrapper does NOT itself decide whether to send. That lives in
 *     @papercrane/email — we just bind dependencies (logger, env-derived
 *     `live` flag) so the call site stays compact.
 *   - We re-export the `TemplateName` and data types for convenience so
 *     route handlers don't need a second import from the package.
 */
import type { FastifyBaseLogger } from "fastify";
import {
  sendEmail as sendEmailRaw,
  type SendEmailInput,
  type SendEmailResult,
  type SenderLogger,
  type TemplateName,
} from "@papercrane/email";

export type { TemplateName, SendEmailInput, SendEmailResult } from "@papercrane/email";

export interface SendEmailDeps {
  logger: FastifyBaseLogger;
}

/**
 * True when we have credentials AND are not running under NODE_ENV=test.
 * Tests should never hit the wire even if a stray RESEND_API_KEY leaks in.
 */
function shouldGoLive(): boolean {
  if (process.env.NODE_ENV === "test") return false;
  return Boolean(process.env.RESEND_API_KEY);
}

/** Adapter: Fastify's logger has the shape we need but typed slightly different. */
function adaptLogger(log: FastifyBaseLogger): SenderLogger {
  return {
    info: (obj, msg) => log.info(obj, msg),
    warn: (obj, msg) => log.warn(obj, msg),
    error: (obj, msg) => log.error(obj, msg),
  };
}

export async function sendEmail<T extends TemplateName>(
  input: SendEmailInput<T>,
  deps: SendEmailDeps,
): Promise<SendEmailResult> {
  return sendEmailRaw(input, {
    live: shouldGoLive(),
    logger: adaptLogger(deps.logger),
  });
}
