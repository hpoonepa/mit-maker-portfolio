/**
 * Webhook delivery — shared types.
 *
 * Kept separate from dispatcher/processor so the API package can import the
 * `WebhookEventName` union without pulling in BullMQ.
 */

/**
 * Every domain event that can trigger a webhook. The literal strings are the
 * wire format — users subscribe by putting them in `webhooks.events[]`.
 *
 * Add new events by:
 *   1. Appending the string here.
 *   2. Calling `dispatcher.dispatch({ event: '...', ... })` from the place the
 *      event happens.
 *   3. Documenting the payload shape in the public webhooks reference.
 */
export type WebhookEventName =
  | 'job.completed'
  | 'job.failed'
  | 'design.top_hit';

/**
 * Envelope wire format. Matches Stripe's event envelope so user-side
 * libraries are interchangeable.
 */
export interface WebhookPayload<T = unknown> {
  /** Unique id per delivery attempt (mirrors `delivery.id`). */
  id: string;
  /** Unix seconds timestamp of event creation. */
  created: number;
  /** Event name; clients pattern-match on this. */
  type: WebhookEventName;
  /** Event-specific data. Shape is documented per-event. */
  data: T;
}

/**
 * BullMQ job payload for a single delivery attempt. The delivery row owns
 * the heavy fields (payload, secret-derived signature inputs); the job only
 * carries a pointer.
 */
export interface DeliveryJob {
  deliveryId: string;
  attempt: number;
}

/**
 * Minimal Queue surface used by the dispatcher + processor. Matches BullMQ's
 * `Queue#add`. Typed thinly so tests can provide a plain object instead of a
 * real BullMQ Queue.
 */
export interface WebhookQueue {
  add(
    name: string,
    data: DeliveryJob,
    opts?: { delay?: number; jobId?: string; removeOnComplete?: boolean | number; removeOnFail?: boolean | number },
  ): Promise<{ id?: string | null | undefined }>;
}

/**
 * Event emitted by the job processor (or any future producer) to the
 * dispatcher. Keep shape small — payload is opaque and gets stamped into
 * the envelope as-is.
 */
export interface DomainEvent<T = unknown> {
  orgId: string;
  event: WebhookEventName;
  payload: T;
}
