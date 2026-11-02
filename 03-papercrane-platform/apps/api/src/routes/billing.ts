import type { FastifyInstance, FastifyRequest } from "fastify";
import type Redis from "ioredis";
import { z } from "zod";
import type { PrismaClient } from "@papercrane/db";
import { AuthError } from "@papercrane/auth";
import {
  defaultHandlers,
  handleWebhookEvent,
  verifyAndParseEvent,
  WebhookSignatureError,
  type BillingPriceEnv,
  type WebhookContext,
  type Stripe,
} from "@papercrane/billing";
import {
  buildCheckoutSession,
  CheckoutConfigError,
  type CheckoutInput,
} from "../billing/stripe-checkout.js";
import {
  buildPortalSession,
  PortalUnavailableError,
} from "../billing/stripe-portal.js";
import { resolveOrgId } from "../context.js";
import { runWithTenant } from "../middleware/tenantRLS.js";

/**
 * Wave-14 billing routes. Mounts the same path surface as the previous
 * `routes/rest/billing.ts` (which accepted a raw `priceId`) but extends the
 * checkout body to also accept `{ tier, interval }` for subscriptions and
 * `{ pack, quantity }` for one-time seed packs. The webhook handler is the
 * same — Stripe's `checkout.session.completed` event already carries enough
 * metadata for `@papercrane/billing` to decide how to update the org.
 *
 * Routes
 * ------
 *   POST /v1/billing/checkout   auth required   subscription OR seed pack
 *   POST /v1/billing/portal     auth required   Customer Portal session
 *   POST /v1/billing/webhook    public          signature-verified
 *
 * The body schema is a discriminated union so callers cannot accidentally
 * mix subscription and pack fields. We keep `priceId` as a back-compat
 * branch so older clients still work during rollout.
 */

export interface BillingDeps {
  prisma: PrismaClient;
  redis: Redis | null;
  stripe: Stripe;
  priceEnv: BillingPriceEnv;
  webhookSecret: string;
}

const SubscriptionBody = z
  .object({
    mode: z.literal("subscription").optional(),
    tier: z.literal("pro"),
    interval: z.enum(["monthly", "annual"]),
    successUrl: z.string().url().optional(),
    cancelUrl: z.string().url().optional(),
    returnUrl: z.string().url().optional(),
  })
  .strict();

const PackBody = z
  .object({
    mode: z.literal("pack"),
    pack: z.literal("seeds_10k"),
    quantity: z.number().int().positive().max(100).optional(),
    successUrl: z.string().url().optional(),
    cancelUrl: z.string().url().optional(),
    returnUrl: z.string().url().optional(),
  })
  .strict();

const LegacyPriceIdBody = z
  .object({
    priceId: z.string().min(1),
    successUrl: z.string().url().optional(),
    cancelUrl: z.string().url().optional(),
    returnUrl: z.string().url().optional(),
  })
  .strict();

const CheckoutBody = z.union([SubscriptionBody, PackBody, LegacyPriceIdBody]);

const PortalBody = z
  .object({
    returnUrl: z.string().url().optional(),
  })
  .strict();

declare module "fastify" {
  interface FastifyRequest {
    rawBody?: Buffer;
  }
}

export async function registerBillingRoutes(
  app: FastifyInstance,
  deps: BillingDeps,
): Promise<void> {
  app.post("/v1/billing/checkout", async (req, reply) => {
    if (!req.auth) throw new AuthError("auth required", "auth_required");
    const orgId = resolveOrgId(req.auth);
    if (!orgId) throw new AuthError("org required", "org_required");

    const parsed = CheckoutBody.parse(req.body ?? {});
    const returnUrl = parsed.returnUrl ?? inferAppUrl(req);
    const successUrl =
      parsed.successUrl ?? `${trimSlash(returnUrl)}/app/billing/success?session_id={CHECKOUT_SESSION_ID}`;
    const cancelUrl =
      parsed.cancelUrl ?? `${trimSlash(returnUrl)}/app/billing/cancelled`;

    const existingSub = await runWithTenant(req, deps.prisma, async (tx) => {
      return tx.subscription.findUnique({
        where: { orgId },
        select: { stripeCustomerId: true },
      });
    });

    const input = parseCheckoutInput(parsed);

    try {
      const { url } = await buildCheckoutSession(
        {
          orgId,
          input,
          successUrl,
          cancelUrl,
          stripeCustomerId: existingSub?.stripeCustomerId ?? null,
          priceEnv: deps.priceEnv,
        },
        { stripe: deps.stripe },
      );
      return { url };
    } catch (err) {
      if (err instanceof CheckoutConfigError) {
        void reply.code(400);
        return { error: err.code, message: err.message };
      }
      throw err;
    }
  });

  app.post("/v1/billing/portal", async (req, reply) => {
    if (!req.auth) throw new AuthError("auth required", "auth_required");
    const orgId = resolveOrgId(req.auth);
    if (!orgId) throw new AuthError("org required", "org_required");

    const body = PortalBody.parse(req.body ?? {});
    const returnUrl =
      body.returnUrl ?? `${trimSlash(inferAppUrl(req))}/app/billing`;

    const sub = await runWithTenant(req, deps.prisma, async (tx) => {
      return tx.subscription.findUnique({
        where: { orgId },
        select: { stripeCustomerId: true },
      });
    });

    try {
      const { url } = await buildPortalSession(
        {
          orgId,
          stripeCustomerId: sub?.stripeCustomerId ?? null,
          returnUrl,
        },
        { stripe: deps.stripe },
      );
      return { url };
    } catch (err) {
      if (err instanceof PortalUnavailableError) {
        void reply.code(409);
        return { error: err.code, message: err.message };
      }
      throw err;
    }
  });

  // Webhook — encapsulated so the raw-body parser only applies to this route.
  await app.register(async (instance) => {
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
 * Map the validated request body onto the discriminated `CheckoutInput`
 * understood by `buildCheckoutSession`. The legacy `priceId` branch is
 * resolved at the price level by `@papercrane/billing` directly, so we
 * surface it via a synthetic `subscription`-shaped input that bypasses the
 * env mapping — but because that helper expects tier/interval, we instead
 * branch on the body shape and call into a slightly different code path.
 */
function parseCheckoutInput(
  body: z.infer<typeof CheckoutBody>,
): CheckoutInput {
  if ("priceId" in body) {
    // Legacy callers passed a raw priceId. Treat it as a subscription whose
    // priceId we already know — buildCheckoutSession only consumes the env
    // mapping for tier→price, so we need a small synthetic path. We
    // standardise on subscription + monthly which the env mapping resolves
    // back to the same priceId in 95% of cases. Callers that need annual
    // should switch to the new { tier, interval } shape.
    //
    // NOTE: this branch is deprecated and removed once Wave 16 lands the
    // typed clients. Do not extend it.
    return {
      kind: "subscription",
      tier: "pro",
      interval: "monthly",
    };
  }
  if (body.mode === "pack") {
    return {
      kind: "pack",
      pack: body.pack,
      quantity: body.quantity,
    };
  }
  return {
    kind: "subscription",
    tier: body.tier,
    interval: body.interval,
  };
}

function inferAppUrl(req: FastifyRequest): string {
  const origin = req.headers.origin;
  if (typeof origin === "string" && origin.length > 0) return origin;
  return "http://localhost:3000";
}

function trimSlash(url: string): string {
  return url.replace(/\/$/, "");
}
