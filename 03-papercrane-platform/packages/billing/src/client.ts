import Stripe from "stripe";

/**
 * Stripe client factory.
 *
 * We pin `apiVersion` so Stripe's SDK doesn't silently upgrade us onto a
 * newer schema when the lockfile refreshes — webhook payload shapes are
 * keyed off the API version and drift would break `constructEvent` typing.
 * The chosen version matches the Stripe SDK 16.x minimum.
 *
 * Callers should use a single client per process. Tests inject their own
 * `Stripe`-shaped mock rather than calling this factory.
 */

export const STRIPE_API_VERSION = "2024-06-20" as const;

export interface StripeClientOptions {
  secretKey: string;
  /** Optional override, primarily used by tests or SDK upgrades. */
  apiVersion?: Stripe.LatestApiVersion;
  /** Optional HTTP timeout in ms. Default 10s — Stripe's recommendation. */
  timeoutMs?: number;
}

export function createStripeClient(opts: StripeClientOptions): Stripe {
  if (!opts.secretKey) {
    throw new Error("createStripeClient: secretKey is required");
  }
  return new Stripe(opts.secretKey, {
    apiVersion: opts.apiVersion ?? STRIPE_API_VERSION,
    timeout: opts.timeoutMs ?? 10_000,
    typescript: true,
  });
}

export type { Stripe };
