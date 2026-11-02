"use client";

/**
 * Stripe Customer Portal launcher.
 *
 * Same shape as `checkout.ts`: POST to our API, receive a hosted URL,
 * redirect. The portal lets users update payment methods, download past
 * invoices, and cancel / resume subscriptions without us building those
 * surfaces ourselves.
 *
 * Route wired at: apps/api/src/routes/rest/billing.ts → POST /v1/billing/portal
 */

import { getApiBaseUrl } from "@/lib/trpc/shared";
import { createSupabaseBrowserClient } from "@/lib/supabase/client";

export interface PortalArgs {
  /**
   * Path the user returns to after closing the portal. Defaults to
   * `/settings/billing`.
   */
  returnPath?: string;
}

export interface PortalClientDeps {
  fetch: typeof fetch;
  navigate: (url: string) => void;
  getAccessToken: () => Promise<string | null>;
  apiBaseUrl: string;
}

export class PortalError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "PortalError";
  }
}

function defaultDeps(): PortalClientDeps {
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

export async function openPortal(
  args: PortalArgs = {},
  depsOverride?: Partial<PortalClientDeps>,
): Promise<void> {
  const deps: PortalClientDeps = {
    ...defaultDeps(),
    ...(depsOverride ?? {}),
  } as PortalClientDeps;

  const token = await deps.getAccessToken();
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };
  if (token) headers["authorization"] = `Bearer ${token}`;

  const origin =
    typeof window !== "undefined" ? window.location.origin : "";
  const returnPath = args.returnPath ?? "/settings/billing";
  const returnUrl = origin ? `${origin}${returnPath}` : undefined;

  const body: Record<string, unknown> = {};
  if (returnUrl) body.returnUrl = returnUrl;

  const res = await deps.fetch(`${deps.apiBaseUrl}/v1/billing/portal`, {
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
    throw new PortalError(
      `portal failed: ${res.status}`,
      res.status,
      detail,
    );
  }

  const payload = (await res.json()) as { url?: unknown };
  if (typeof payload.url !== "string" || !payload.url.startsWith("http")) {
    throw new PortalError("portal response missing url", res.status, payload);
  }

  deps.navigate(payload.url);
}
