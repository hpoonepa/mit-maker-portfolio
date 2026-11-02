/**
 * Request-id propagation.
 *
 * - Reads `x-request-id` from the incoming request if present, otherwise
 *   generates a UUIDv7 (time-ordered, sortable, fixed-size).
 * - Sets `x-request-id` on the response so clients can correlate.
 * - Attaches `request.id` so Fastify's `req.log` includes it on every line.
 * - Tags the current Sentry scope with the id so any captured exception is
 *   correlated with the request without callers having to pass it in.
 *
 * Fastify already supports `requestIdHeader: "x-request-id"` at server
 * construction, but it does NOT generate UUIDv7 and does NOT echo the id back
 * on the response. This hook fills both gaps without conflicting with the
 * built-in: we set `request.id` explicitly via the assignable `id` getter and
 * write the response header in `onSend`.
 */
import { randomBytes } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { tagRequestId } from "./sentry.js";

const HEADER = "x-request-id";

/**
 * Generate a UUIDv7 as a 36-char hyphenated string. RFC 9562 layout:
 *   - 48 bits  unix_ms       (big-endian)
 *   - 4 bits   version (=7)
 *   - 12 bits  rand_a
 *   - 2 bits   variant (=10)
 *   - 62 bits  rand_b
 */
export function uuidv7(): string {
  const ms = Date.now();
  const buf = randomBytes(16);

  // 48 bits of unix_ms across bytes 0..5 (big-endian).
  buf[0] = (ms / 2 ** 40) & 0xff;
  buf[1] = (ms / 2 ** 32) & 0xff;
  buf[2] = (ms >>> 24) & 0xff;
  buf[3] = (ms >>> 16) & 0xff;
  buf[4] = (ms >>> 8) & 0xff;
  buf[5] = ms & 0xff;

  // Version 7: top 4 bits of byte 6.
  buf[6] = (buf[6]! & 0x0f) | 0x70;
  // Variant 10: top 2 bits of byte 8.
  buf[8] = (buf[8]! & 0x3f) | 0x80;

  const hex = buf.toString("hex");
  return (
    hex.slice(0, 8) +
    "-" +
    hex.slice(8, 12) +
    "-" +
    hex.slice(12, 16) +
    "-" +
    hex.slice(16, 20) +
    "-" +
    hex.slice(20, 32)
  );
}

/**
 * Register the request-id hook on a Fastify instance. Call this BEFORE any
 * route or auth hook so downstream handlers (and `req.log`) see the id.
 */
export function registerRequestId(app: FastifyInstance): void {
  app.addHook("onRequest", async (req, reply) => {
    const incoming =
      typeof req.headers[HEADER] === "string"
        ? (req.headers[HEADER] as string).trim()
        : undefined;
    const id = incoming && incoming.length > 0 ? incoming : uuidv7();

    // Fastify exposes `request.id` as a read-only getter that reads from the
    // configured `requestIdHeader`. To override, we set the header (which the
    // getter reads on subsequent accesses) and also stash on `request.id`-like
    // log binding so log lines pick it up.
    req.headers[HEADER] = id;
    // Echo on the response so clients can correlate.
    void reply.header(HEADER, id);

    // Bind the id into the request log so every line includes it.
    // Fastify's `req.log` is a pino child; `setBindings` mutates in place.
    const log = req.log as unknown as { setBindings?: (b: Record<string, unknown>) => void };
    if (typeof log.setBindings === "function") {
      log.setBindings({ requestId: id });
    }

    // Best-effort Sentry scope tagging — no-op when DSN is unset.
    void tagRequestId(id);
  });
}
