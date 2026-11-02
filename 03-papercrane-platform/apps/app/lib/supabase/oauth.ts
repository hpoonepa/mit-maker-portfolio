"use client";

import { createSupabaseBrowserClient } from "@/lib/supabase/client";

export type OAuthProvider = "google" | "github";

export interface OAuthSignInResult {
  ok: boolean;
  error?: string;
}

export type OAuthProviderAvailability = Record<OAuthProvider, boolean>;

/** Read the provider switches from Supabase's public Auth settings endpoint. */
export async function getOAuthProviderAvailability(
  request: typeof fetch = fetch,
): Promise<OAuthProviderAvailability> {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) return { google: false, github: false };

  const response = await request(`${url}/auth/v1/settings`, {
    headers: { apikey: anonKey },
  });
  if (!response.ok) {
    throw new Error(`Supabase provider settings returned ${response.status}`);
  }
  const settings = (await response.json()) as {
    external?: Partial<Record<OAuthProvider, boolean>>;
  };
  return {
    google: settings.external?.google === true,
    github: settings.external?.github === true,
  };
}

/**
 * Build the absolute callback URL for OAuth redirects.
 *
 * Prefers NEXT_PUBLIC_APP_URL when set so prod deploys hand back to the canonical
 * domain even if the OAuth tab opened on a preview URL. Falls back to
 * `window.location.origin` in dev / preview environments.
 */
export function buildCallbackUrl(
  redirectTo: string,
  inviteCode?: string,
): string {
  const appUrl =
    process.env.NEXT_PUBLIC_APP_URL ??
    (typeof window !== "undefined" ? window.location.origin : "");
  const safeTarget = redirectTo.startsWith("/") ? redirectTo : "/app";
  const callback = new URL("/auth/callback", appUrl);
  callback.searchParams.set("redirectTo", safeTarget);
  if (inviteCode?.trim()) {
    callback.searchParams.set("invite", inviteCode.trim().toUpperCase());
  }
  return callback.toString();
}

/**
 * Kick off an OAuth sign-in via Supabase.
 *
 * On success the browser is redirected to the provider; on failure we return
 * the error message so the caller can surface it. We never log the message -
 * Supabase error strings can include user identifiers.
 */
export async function signInWithProvider(
  provider: OAuthProvider,
  redirectTo = "/app",
  inviteCode?: string,
): Promise<OAuthSignInResult> {
  const supabase = createSupabaseBrowserClient();
  const { error } = await supabase.auth.signInWithOAuth({
    provider,
    options: {
      redirectTo: buildCallbackUrl(redirectTo, inviteCode),
    },
  });
  if (error) return { ok: false, error: error.message };
  return { ok: true };
}
