/**
 * Wire encoding for JobEvents.
 *
 * The worker `JSON.stringify`s a JobEvent and `PUBLISH`es to Redis; the
 * orchestrator SSE handler reads the message, validates it through zod,
 * and forwards it to the client. Any producer that skips validation
 * is a bug — this module is the only blessed path.
 */

import { JobEventSchema, type JobEvent } from './events';

/** Serialize a JobEvent to a JSON string suitable for Redis pubsub. */
export function serializeEvent(event: JobEvent): string {
  return JSON.stringify(event);
}

/**
 * Parse + validate a wire message. Throws `SyntaxError` for malformed
 * JSON and `zod.ZodError` for schema violations.
 */
export function deserializeEvent(wire: string): JobEvent {
  const raw = JSON.parse(wire) as unknown;
  return JobEventSchema.parse(raw);
}

/** Non-throwing variant — returns `null` on any error. */
export function tryDeserializeEvent(wire: string): JobEvent | null {
  try {
    return deserializeEvent(wire);
  } catch {
    return null;
  }
}
