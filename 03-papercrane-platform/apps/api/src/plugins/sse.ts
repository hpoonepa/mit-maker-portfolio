import type { FastifyInstance, FastifyReply } from "fastify";
import fp from "fastify-plugin";

/**
 * SSE (Server-Sent Events) helpers.
 *
 * Fastify streams body over a raw reply. For SSE we need to:
 *   - set Content-Type: text/event-stream
 *   - disable compression buffering
 *   - keep the connection open and flush on each event
 *   - send periodic keep-alive comments so proxies don't cut the socket
 *
 * Callers use `reply.sse.open()` to set headers, `reply.sse.send(payload)` per
 * event, and `reply.sse.close()` when the stream is done. A `signal` is
 * attached so handlers can abort work when the client disconnects.
 */

export interface SSEEvent {
  /** Event type, becomes `event:` field. Defaults to `message`. */
  event?: string;
  /** JSON-serializable payload, becomes `data:` field (stringified). */
  data: unknown;
  /** Optional event id, becomes `id:` field (clients use it on reconnect). */
  id?: string;
  /** Optional retry hint, milliseconds, becomes `retry:` field. */
  retryMs?: number;
}

export interface SSEStream {
  /** Send the headers and an initial keep-alive comment. */
  open(): void;
  /** Emit an event. Returns false if the stream is already closed. */
  send(event: SSEEvent): boolean;
  /** Fire a keep-alive comment (empty event, `:` prefix per spec). */
  ping(): void;
  /** End the stream. Safe to call multiple times. */
  close(): void;
  /** AbortSignal that fires when the client disconnects. */
  readonly signal: AbortSignal;
}

function encodeEvent(event: SSEEvent): string {
  const out: string[] = [];
  if (event.id !== undefined) out.push(`id: ${event.id}`);
  if (event.event !== undefined) out.push(`event: ${event.event}`);
  if (event.retryMs !== undefined) out.push(`retry: ${event.retryMs}`);
  const data =
    typeof event.data === "string" ? event.data : JSON.stringify(event.data);
  // Multi-line data must be split per the EventSource spec.
  for (const line of data.split(/\r?\n/)) {
    out.push(`data: ${line}`);
  }
  out.push("", "");
  return out.join("\n");
}

/**
 * Attach an SSE helper to a reply. Caller must invoke `open()` first.
 */
export function attachSSE(reply: FastifyReply): SSEStream {
  const controller = new AbortController();
  let closed = false;

  const raw = reply.raw;
  raw.on("close", () => {
    closed = true;
    controller.abort();
  });

  return {
    get signal() {
      return controller.signal;
    },
    open(): void {
      reply.hijack();
      raw.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      });
      raw.write(": ok\n\n");
    },
    send(event: SSEEvent): boolean {
      if (closed) return false;
      raw.write(encodeEvent(event));
      return true;
    },
    ping(): void {
      if (closed) return;
      raw.write(": ping\n\n");
    },
    close(): void {
      if (closed) return;
      closed = true;
      raw.end();
    },
  };
}

/**
 * Fastify plugin: decorates the reply with `openSSE()` which returns a fresh
 * {@link SSEStream}. Callers own the lifecycle — they MUST call `open()`
 * before `send()` and `close()` when done (or on client disconnect via the
 * provided `signal`).
 *
 * We expose a method rather than a lazy getter because Fastify's
 * `decorateReply` path for getters is brittle across versions; a plain
 * method keeps the surface small and predictable.
 */
export const ssePlugin = fp(async function ssePluginImpl(
  app: FastifyInstance,
): Promise<void> {
  app.decorateReply("openSSE", function openSSEImpl(this: FastifyReply) {
    return attachSSE(this);
  });
});

declare module "fastify" {
  interface FastifyReply {
    openSSE(): SSEStream;
  }
}
