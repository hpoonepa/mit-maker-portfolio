"use client";

/**
 * Client-side Stripe Checkout launcher.
 *
 * The browser never talks to Stripe directly. Flow:
 *
 *   1. User clicks "Subscribe" in UpgradeModal.
 *   2. This helper POSTs to `apps/api` → `POST /v1/billing/checkout`.
 *   3. The API calls `stripe.checkout.sessions.create(...)` and returns
 *      `{ url: "https://checkout.stripe.com/c/pay/cs_test_..." }`.
 *   4. We `window.location = url`: the user is now on Stripe's hosted page.
 *   5. On success Stripe redirects to `successUrl` (default
 *      `<origin>/settings/billing?checkout=success`).
 *   6. The webhook (`checkout.session.completed` + `customer.subscription.*`)
 *      flips `Subscription.tier` in Postgres; the dashboard refetches.
 *
 * We deliberately DON'T import `@stripe/stripe-js`: that would load Stripe's
 * client SDK (~90KB gzip) just to do a redirect. `window.location` is enough.
 */

import { getApiBaseUrl } from "@/lib/trpc/shared";
import { createSupabaseBrowserClient } from "@/lib/supabase/client";

export interface CheckoutArgs {
  /** Stripe price id: pick from env (STRIPE_PRICE_PRO_MONTHLY / ANNUAL). */
  priceId: string;
  /**
   * Path (relative to the current origin) the user lands on after Stripe
   * Checkout completes or is cancelled. The API uses it to build the full
   * success/cancel URLs. Defaults to `/settings/billing`.
   */
  returnPath?: string;
}

/**
 * Injected dependencies so tests can mock fetch + window navigation. In
 * production, pass nothing and the default impls use the browser globals.
 */
export interface CheckoutClientDeps {
  fetch: typeof fetch;
  navigate: (url: string) => void;
  getAccessToken: () => Promise<string | null>;
  apiBaseUrl: string;
}

export class CheckoutError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "CheckoutError";
  }
}

/** Default dep factory: pulls Supabase session + sane apiBaseUrl + nav. */
function defaultDeps(): CheckoutClientDeps {
  return {
    fetch: window.fetch.bind(window),
    navigate: (url: string) => {
      window.location.href = url;
    },
    async getAccessToken() {
      const supabase = createSupabaseBrowserClient();
      const {
        data: { session },
      } = await supabase.auth.getSession();
      return session?.access_token ?? null;
    },
    apiBaseUrl: getApiBaseUrl() || window.location.origin,
  };
}

/**
 * POST /v1/billing/checkout and redirect the browser to the Stripe Checkout
 * URL. Throws {@link CheckoutError} on API / schema failures: callers should
 * surface a toast.
 */
export async function redirectToCheckout(
  args: CheckoutArgs,
  depsOverride?: Partial<CheckoutClientDeps>,
): Promise<void> {
  const deps: CheckoutClientDeps = {
    ...defaultDeps(),
    ...(depsOverride ?? {}),
  } as CheckoutClientDeps;

  const token = await deps.getAccessToken();
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };
  if (token) headers["authorization"] = `Bearer ${token}`;

  const origin =
    typeof window !== "undefined" ? window.location.origin : "";
  const returnPath = args.returnPath ?? "/settings/billing";
  const returnUrl = origin ? `${origin}${returnPath}` : undefined;

  const body: Record<string, unknown> = { priceId: args.priceId };
  if (returnUrl) body.returnUrl = returnUrl;

  const res = await deps.fetch(`${deps.apiBaseUrl}/v1/billing/checkout`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    credentials: "include",
  });

  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = await res.json();
    } catch {
      // ignore
    }
    throw new CheckoutError(
      `checkout failed: ${res.status}`,
      res.status,
      detail,
    );
  }

  const payload = (await res.json()) as { url?: unknown };
  if (typeof payload.url !== "string" || !payload.url.startsWith("http")) {
    throw new CheckoutError(
      "checkout response missing url",
      res.status,
      payload,
    );
  }

  deps.navigate(payload.url);
}
