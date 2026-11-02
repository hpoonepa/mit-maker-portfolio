import type { FastifyInstance, FastifyRequest } from "fastify";
import type Redis from "ioredis";
import { z } from "zod";
import type { PrismaClient } from "@papercrane/db";
import { AuthError } from "@papercrane/auth";
import {
  createCheckoutSession,
  createPortalSession,
  defaultHandlers,
  handleWebhookEvent,
  verifyAndParseEvent,
  WebhookSignatureError,
  type BillingPriceEnv,
  type WebhookContext,
  type Stripe,
} from "@papercrane/billing";
import { resolveOrgId } from "../../context.js";
import { runWithTenant } from "../../middleware/tenantRLS.js";

/**
 * Billing HTTP routes.
 *
 *   POST /v1/billing/checkout   auth required   → returns Stripe Checkout URL
 *   POST /v1/billing/portal     auth required   → returns Customer Portal URL
 *   POST /v1/billing/webhook    public          → signature-verified, raw body
 *
 * Raw-body handling
 * -----------------
 * The webhook endpoint MUST receive bytes untouched — Stripe's HMAC is over
 * the exact payload. We register a scoped `application/json` content-type
 * parser on the Fastify child instance that handles the webhook route, which
 * stashes the raw Buffer on `request.rawBody` AND parses JSON normally for
 * anything the route might read off `request.body`. The scoping relies on
 * Fastify's plugin encapsulation: the parser only applies inside the inner
 * plugin we create below.
 */

export interface BillingDeps {
  prisma: PrismaClient;
  redis: Redis | null;
  stripe: Stripe;
  priceEnv: BillingPriceEnv;
  webhookSecret: string;
}

const CheckoutBodySchema = z
  .object({
    priceId: z.string().min(1),
    successUrl: z.string().url().optional(),
    cancelUrl: z.string().url().optional(),
    returnUrl: z.string().url().optional(),
  })
  .strict();

const PortalBodySchema = z
  .object({
    returnUrl: z.string().url().optional(),
  })
  .strict();

// Augment FastifyRequest with the raw-body cache the webhook parser fills.
declare module "fastify" {
  interface FastifyRequest {
    rawBody?: Buffer;
  }
}

export async function registerBillingRoutes(
  app: FastifyInstance,
  deps: BillingDeps,
): Promise<void> {
  // ─── Authenticated endpoints ──────────────────────────────────────────────

  app.post("/v1/billing/checkout", async (req) => {
    if (!req.auth) throw new AuthError("auth required", "auth_required");
    const orgId = resolveOrgId(req.auth);
    if (!orgId) throw new AuthError("org required", "org_required");

    const body = CheckoutBodySchema.parse(req.body ?? {});

    const returnUrl = body.returnUrl ?? inferAppUrl(req);
    const successUrl =
      body.successUrl ?? `${returnUrl}?checkout=success`;
    const cancelUrl = body.cancelUrl ?? `${returnUrl}?checkout=cancelled`;

    // Look up an existing Stripe Customer id so we don't orphan-create one
    // per checkout attempt. Read from the Subscription mirror — if the org
    // never paid before, there is no row and Stripe will create the customer
    // inside Checkout.
    const existingSub = await runWithTenant(req, deps.prisma, async (tx) => {
      return tx.subscription.findUnique({
        where: { orgId },
        select: { stripeCustomerId: true },
      });
    });

    const { url } = await createCheckoutSession(
      {
        orgId,
        priceId: body.priceId,
        successUrl,
        cancelUrl,
        stripeCustomerId: existingSub?.stripeCustomerId ?? null,
      },
      { stripe: deps.stripe },
    );

    return { url };
  });

  app.post("/v1/billing/portal", async (req) => {
    if (!req.auth) throw new AuthError("auth required", "auth_required");
    const orgId = resolveOrgId(req.auth);
    if (!orgId) throw new AuthError("org required", "org_required");

    const body = PortalBodySchema.parse(req.body ?? {});
    const returnUrl = body.returnUrl ?? inferAppUrl(req);

    const sub = await runWithTenant(req, deps.prisma, async (tx) => {
      return tx.subscription.findUnique({
        where: { orgId },
        select: { stripeCustomerId: true },
      });
    });
    if (!sub?.stripeCustomerId) {
      throw new AuthError(
        "org has no stripe customer yet",
        "no_stripe_customer",
      );
    }

    const { url } = await createPortalSession(
      { stripeCustomerId: sub.stripeCustomerId, returnUrl },
      { stripe: deps.stripe },
    );
    return { url };
  });

  // ─── Webhook (public, signature-verified, raw body) ──────────────────────
  // Encapsulated in a child plugin so the raw-body content-type parser only
  // applies to the webhook route. Outside this scope, the default JSON parser
  // handles bodies as usual.
  await app.register(async (instance) => {
    // Scoped parser: only this encapsulated context uses it. The parser
    // receives the raw Buffer (parseAs=buffer), stashes it on the request
    // for signature verification, and then parses JSON so anything reading
    // `req.body` still sees structured data.
    instance.addContentTypeParser(
      "application/json",
      { parseAs: "buffer" },
      (req, body, done) => {
        try {
          const raw = body as Buffer;
          req.rawBody = raw;
          const text = raw.length ? raw.toString("utf8") : "";
          const parsed = text.length ? JSON.parse(text) : {};
          done(null, parsed);
        } catch (err) {
          done(err as Error, undefined);
        }
      },
    );

    instance.post(
      "/v1/billing/webhook",
      { config: { public: true } },
      async (req, reply) => {
        const rawBody = req.rawBody ?? Buffer.alloc(0);

        const signature = req.headers["stripe-signature"];
        const sig = Array.isArray(signature) ? signature[0] : signature;

        let event: Stripe.Event;
        try {
          event = verifyAndParseEvent(
            { rawBody, signature: sig },
            { stripe: deps.stripe, webhookSecret: deps.webhookSecret },
          );
        } catch (err) {
          if (err instanceof WebhookSignatureError) {
            req.log.warn(
              { err: err.message },
              "billing.webhook: signature verification failed",
            );
            void reply.code(400);
            return { error: "invalid_signature" };
          }
          throw err;
        }

        const ctx: WebhookContext = {
          prisma: deps.prisma,
          redis: deps.redis as WebhookContext["redis"],
          logger: req.log,
          priceEnv: deps.priceEnv,
          handlers: defaultHandlers,
        };

        try {
          await handleWebhookEvent(event, ctx);
        } catch (err) {
          // Log but return 500 so Stripe retries. Handlers that throw are
          // unexpected — the 7-day redis dedup TTL covers retries safely.
          req.log.error(
            { err, eventId: event.id, eventType: event.type },
            "billing.webhook: handler failed",
          );
          void reply.code(500);
          return { error: "handler_failed" };
        }

        return { received: true };
      },
    );
  });
}

/**
 * Fallback return URL when the caller doesn't specify one. Derived from the
 * request `origin` header when present, otherwise localhost dev default.
 */
function inferAppUrl(req: FastifyRequest): string {
  const origin = req.headers.origin;
  if (typeof origin === "string" && origin.length > 0) return origin;
  return "http://localhost:3000/settings/billing";
}
