/**
 * Billing router — dashboard-facing surface for the subscription state and
 * Stripe Checkout / Customer Portal launchers.
 *
 * Shape
 * -----
 *   billing.currentSubscription.useQuery()   → row from `Subscription` or null
 *   billing.invoices.useQuery({ limit, cursor }) → proxied from apps/api
 *   billing.createCheckout.useMutation(...)  → proxied to apps/api which calls Stripe
 *
 * Why proxy instead of creating the Checkout Session here?
 * --------------------------------------------------------
 * The Stripe secret key lives only in `apps/api` (plan 01 §4, plan 05 §3).
 * tRPC runs in Next's RSC + Fastify; we deliberately keep Stripe creds out
 * of the Next process. `createCheckout` therefore does a server-to-server
 * call to `POST /v1/billing/checkout` using the REST route that already
 * wraps `@papercrane/billing`'s `createCheckoutSession`. Forward the
 * caller's auth as a Bearer so the API identifies the org correctly.
 *
 * Read procedures (`currentSubscription`, a cached read-from-DB) still
 * use the RLS-scoped Prisma path so row-level security holds.
 */

import { z } from 'zod';
import { router, publicProcedure, TRPCError } from '../trpc.js';
import { requireAuth } from '../middleware/auth.js';

const protectedProcedure = publicProcedure.use(requireAuth);

const SubscriptionSchema = z
  .object({
    id: z.string(),
    orgId: z.string(),
    stripeCustomerId: z.string(),
    stripeSubscriptionId: z.string(),
    status: z.string(),
    tier: z.string(),
    currentPeriodEnd: z.union([z.date(), z.string()]),
    createdAt: z.union([z.date(), z.string()]).optional(),
    updatedAt: z.union([z.date(), z.string()]).optional(),
  })
  .nullable();

const InvoiceSchema = z.object({
  id: z.string(),
  number: z.string().nullable(),
  amountPaid: z.number(),
  currency: z.string(),
  status: z.string(),
  created: z.string(),
  hostedInvoiceUrl: z.string().nullable(),
  invoicePdf: z.string().nullable(),
});

const InvoicesInput = z
  .object({
    limit: z.number().int().positive().max(50).optional(),
    cursor: z.string().nullish(),
  })
  .strict();

const InvoicesOutput = z.object({
  items: z.array(InvoiceSchema),
  nextCursor: z.string().nullable(),
});

const CheckoutInput = z
  .object({
    priceId: z.string().min(1),
    returnPath: z.string().optional(),
  })
  .strict();

const CheckoutOutput = z.object({
  url: z.string().url(),
});

/**
 * Wave-14 typed checkout shape. Callers describe what they want
 * (`tier+interval` for a subscription, `pack` for a one-time purchase) and
 * the API resolves that to a Stripe price id from env. Keeps Stripe creds
 * out of the Next.js process.
 */
const CreateCheckoutSessionInput = z.union([
  z
    .object({
      mode: z.literal("subscription").optional(),
      tier: z.literal("pro"),
      interval: z.enum(["monthly", "annual"]),
      returnPath: z.string().optional(),
    })
    .strict(),
  z
    .object({
      mode: z.literal("pack"),
      pack: z.literal("seeds_10k"),
      quantity: z.number().int().positive().max(100).optional(),
      returnPath: z.string().optional(),
    })
    .strict(),
]);

const CreateCheckoutSessionOutput = z.object({
  url: z.string().url(),
});

const CreatePortalSessionInput = z
  .object({
    returnPath: z.string().optional(),
  })
  .strict();

const CreatePortalSessionOutput = z.object({
  url: z.string().url(),
});

/**
 * Resolve the apps/api base URL from env. Falls back to localhost for
 * dev so the test harness doesn't need to configure anything unless it
 * wants to.
 */
function resolveApiBaseUrl(): string {
  return (
    process.env.API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    'http://localhost:3001'
  );
}

/**
 * Pull the Bearer token from the inbound request headers so we can proxy
 * to apps/api as the same user. The tRPC context wraps the raw request.
 */
function extractBearer(
  req: { headers: Record<string, string | string[] | undefined> } | undefined,
): string | null {
  if (!req) return null;
  const h = req.headers['authorization'] ?? req.headers['Authorization'];
  const v = Array.isArray(h) ? h[0] : h;
  if (!v || typeof v !== 'string') return null;
  return v.startsWith('Bearer ') ? v : null;
}

export const billingRouter = router({
  currentSubscription: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/billing/subscription',
        tags: ['billing'],
        summary: 'Get the current Subscription mirror row (null for Free)',
        protect: true,
      },
    })
    .input(z.void())
    .output(SubscriptionSchema)
    .query(async ({ ctx }) => {
      const row = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, async (tx) => {
        const client = tx as unknown as {
          subscription: {
            findUnique: (args: unknown) => Promise<unknown | null>;
          };
        };
        return client.subscription.findUnique({
          where: { orgId: ctx.auth!.orgId },
        });
      });
      return (row as z.infer<typeof SubscriptionSchema>) ?? null;
    }),

  invoices: protectedProcedure
    .meta({
      openapi: {
        method: 'GET',
        path: '/billing/invoices',
        tags: ['billing'],
        summary: 'Paginated list of past invoices for the caller’s org',
        protect: true,
      },
    })
    .input(InvoicesInput)
    .output(InvoicesOutput)
    .query(async ({ ctx, input }) => {
      // Invoices live in Stripe — there is no mirror table. Proxy to the
      // REST route which reads from Stripe with the org's customer id.
      const base = resolveApiBaseUrl();
      const qs = new URLSearchParams();
      if (input.limit) qs.set('limit', String(input.limit));
      if (input.cursor) qs.set('cursor', input.cursor);
      const url = `${base.replace(/\/$/, '')}/v1/billing/invoices${qs.size ? `?${qs.toString()}` : ''}`;

      const headers: Record<string, string> = { accept: 'application/json' };
      const bearer = extractBearer(ctx.req);
      if (bearer) headers['authorization'] = bearer;

      const res = await fetch(url, { headers });
      if (!res.ok) {
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: `invoices proxy failed: ${res.status}`,
        });
      }
      const payload = (await res.json()) as z.infer<typeof InvoicesOutput>;
      return {
        items: payload.items ?? [],
        nextCursor: payload.nextCursor ?? null,
      };
    }),

  createCheckout: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/billing/checkout',
        tags: ['billing'],
        summary: 'Proxy to apps/api to create a Stripe Checkout session',
        protect: true,
      },
    })
    .input(CheckoutInput)
    .output(CheckoutOutput)
    .mutation(async ({ ctx, input }) => {
      const base = resolveApiBaseUrl();
      const url = `${base.replace(/\/$/, '')}/v1/billing/checkout`;

      const headers: Record<string, string> = {
        'content-type': 'application/json',
        accept: 'application/json',
      };
      const bearer = extractBearer(ctx.req);
      if (bearer) headers['authorization'] = bearer;

      const body: Record<string, unknown> = { priceId: input.priceId };
      if (input.returnPath) {
        // We don't know the browser origin from the server — leave returnUrl
        // off and let the API's `inferAppUrl` use the request Origin. Pass
        // the path through so tests can assert it.
        body.returnPath = input.returnPath;
      }

      const res = await fetch(url, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        let detail: unknown = null;
        try {
          detail = await res.json();
        } catch {
          /* ignore */
        }
        throw new TRPCError({
          code: 'BAD_REQUEST',
          message: `checkout proxy failed: ${res.status}`,
          cause: detail,
        });
      }
      const payload = (await res.json()) as { url?: unknown };
      if (typeof payload.url !== 'string') {
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'checkout response missing url',
        });
      }
      return { url: payload.url };
    }),

  /**
   * Wave-14 typed Checkout launcher. Prefer this over `createCheckout` —
   * it accepts `{ tier, interval }` for subscriptions and `{ pack }` for
   * one-time top-ups, lets the API resolve price ids from env, and never
   * exposes raw price strings to the browser bundle.
   */
  createCheckoutSession: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/billing/checkout-session',
        tags: ['billing'],
        summary: 'Create a Stripe Checkout session by tier or seed pack',
        protect: true,
      },
    })
    .input(CreateCheckoutSessionInput)
    .output(CreateCheckoutSessionOutput)
    .mutation(async ({ ctx, input }) => {
      const base = resolveApiBaseUrl();
      const url = `${base.replace(/\/$/, '')}/v1/billing/checkout`;

      const headers: Record<string, string> = {
        'content-type': 'application/json',
        accept: 'application/json',
      };
      const bearer = extractBearer(ctx.req);
      if (bearer) headers['authorization'] = bearer;

      const body: Record<string, unknown> =
        'pack' in input
          ? {
              mode: 'pack',
              pack: input.pack,
              ...(input.quantity ? { quantity: input.quantity } : {}),
            }
          : {
              tier: input.tier,
              interval: input.interval,
            };
      if (input.returnPath) body.returnPath = input.returnPath;

      const res = await fetch(url, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        type ProxyError = { error?: string; message?: string };
        let detail: ProxyError | null = null;
        try {
          detail = (await res.json()) as ProxyError;
        } catch {
          /* ignore */
        }
        throw new TRPCError({
          code: 'BAD_REQUEST',
          message: detail?.message ?? `checkout-session proxy failed: ${res.status}`,
          cause: detail,
        });
      }
      const payload = (await res.json()) as { url?: unknown };
      if (typeof payload.url !== 'string') {
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'checkout-session response missing url',
        });
      }
      return { url: payload.url };
    }),

  /**
   * Customer Portal session for managing subscription, payment methods,
   * downgrades, and cancellations. Requires the org to already have a
   * Stripe Customer (i.e. they completed checkout at least once).
   */
  createPortalSession: protectedProcedure
    .meta({
      openapi: {
        method: 'POST',
        path: '/billing/portal-session',
        tags: ['billing'],
        summary: 'Create a Stripe Customer Portal session',
        protect: true,
      },
    })
    .input(CreatePortalSessionInput)
    .output(CreatePortalSessionOutput)
    .mutation(async ({ ctx, input }) => {
      const base = resolveApiBaseUrl();
      const url = `${base.replace(/\/$/, '')}/v1/billing/portal`;

      const headers: Record<string, string> = {
        'content-type': 'application/json',
        accept: 'application/json',
      };
      const bearer = extractBearer(ctx.req);
      if (bearer) headers['authorization'] = bearer;

      const body: Record<string, unknown> = {};
      if (input.returnPath) body.returnPath = input.returnPath;

      const res = await fetch(url, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        type ProxyError = { error?: string; message?: string };
        let detail: ProxyError | null = null;
        try {
          detail = (await res.json()) as ProxyError;
        } catch {
          /* ignore */
        }
        // 409 → no_stripe_customer; surface as a typed PRECONDITION_FAILED.
        if (res.status === 409) {
          throw new TRPCError({
            code: 'PRECONDITION_FAILED',
            message:
              detail?.message ??
              'org has no Stripe customer yet — subscribe first',
            cause: detail,
          });
        }
        throw new TRPCError({
          code: 'BAD_REQUEST',
          message: detail?.message ?? `portal proxy failed: ${res.status}`,
          cause: detail,
        });
      }
      const payload = (await res.json()) as { url?: unknown };
      if (typeof payload.url !== 'string') {
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'portal response missing url',
        });
      }
      return { url: payload.url };
    }),
});
