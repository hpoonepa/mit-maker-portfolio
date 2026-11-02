import type Stripe from "stripe";

/**
 * Stripe webhook signature verification.
 *
 * The heavy lifting lives in `stripe.webhooks.constructEvent` — we just wrap
 * it so call sites (API route + tests) don't have to thread the Stripe
 * client into their business logic directly.
 *
 * IMPORTANT: `rawBody` MUST be the untouched request bytes. If Fastify's
 * default JSON body-parser ran on it, the computed HMAC will not match and
 * verification will fail. The API route uses a custom
 * application/json parser on `/v1/billing/webhook` that preserves the Buffer.
 */

export interface VerifyInput {
  rawBody: Buffer | string;
  /** The value of the `Stripe-Signature` header. */
  signature: string | undefined;
}

export interface VerifyDeps {
  stripe: Pick<Stripe, "webhooks">;
  webhookSecret: string;
}

export class WebhookSignatureError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WebhookSignatureError";
  }
}

export function verifyAndParseEvent(
  input: VerifyInput,
  deps: VerifyDeps,
): Stripe.Event {
  if (!input.signature) {
    throw new WebhookSignatureError("missing Stripe-Signature header");
  }
  if (!deps.webhookSecret) {
    throw new WebhookSignatureError("webhook secret not configured");
  }
  try {
    return deps.stripe.webhooks.constructEvent(
      input.rawBody,
      input.signature,
      deps.webhookSecret,
    );
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    throw new WebhookSignatureError(`invalid signature: ${msg}`);
  }
}
