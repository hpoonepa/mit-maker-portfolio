"use client";

/**
 * Dashboard variant of the cookie banner.
 *
 * Logged-in users have already accepted the marketing-site cookie banner
 * during sign-up (their first papercrane.bio visit), so we do NOT
 * re-prompt inside the app. The dashboard only sets strictly-necessary
 * cookies (Supabase auth + CSRF) and stores preferences in `localStorage`.
 *
 * This file exists so other parts of the app can mount a no-op slot without
 * breaking imports, and so that if we ever introduce in-app analytics that
 * require fresh consent we have a clear single place to wire it in.
 */
export function CookieBannerInDashboard(): null {
  // Intentional no-op. See file header.
  return null;
}
