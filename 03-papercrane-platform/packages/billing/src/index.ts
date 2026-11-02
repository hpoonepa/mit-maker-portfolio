/**
 * @papercrane/billing — Stripe integration.
 *
 * Pure domain package — no Fastify, no Express. Callers hand us a request's
 * raw body + signature and we return parsed events / URLs. The API service
 * wires these exports into its routes (apps/api/src/routes/rest/billing.ts).
 */

export { createStripeClient, STRIPE_API_VERSION, type Stripe } from "./client.js";
export type { StripeClientOptions } from "./client.js";

export {
  createCheckoutSession,
  type CreateCheckoutSessionArgs,
  type CheckoutSessionResult,
  type CheckoutDeps,
} from "./checkout.js";

export {
  createPortalSession,
  type CreatePortalSessionArgs,
  type PortalSessionResult,
  type PortalDeps,
} from "./portal.js";

export {
  verifyAndParseEvent,
  WebhookSignatureError,
  type VerifyInput,
  type VerifyDeps,
} from "./verifySignature.js";

export {
  handleWebhookEvent,
  defaultHandlers,
  type WebhookContext,
  type WebhookLogger,
  type WebhookRedis,
  type WebhookHandlerSeam,
} from "./webhooks.js";

export {
  resolvePriceConfig,
  isProPrice,
  proPriceConfig,
  freePriceConfig,
  proTierFlags,
  freeTierFlags,
  PRO_SEEDS_QUOTA,
  FREE_SEEDS_QUOTA,
  type PriceConfig,
  type TierFlags,
  type OrgTier,
  type BillingPriceEnv,
} from "./tiers.js";

export { handleSubscriptionEvent } from "./handlers/subscription.js";
export { handleInvoiceEvent } from "./handlers/invoice.js";
export { handleCheckoutCompleted } from "./handlers/checkout.js";

export {
  estimateJobCost,
  actualCostFromModalSeconds,
  GPU_PRICE_PER_SECOND_USD,
  DEFAULT_FALLBACK_GPU,
  DEFAULT_SECONDS_PER_DESIGN,
  type EstimateJobCostOpts,
  type EstimateJobCostResult,
  type EstimateJobCostBreakdown,
} from "./gpuCost.js";
