/**
 * Cross-deployment link helpers.
 *
 * `apps/web` serves the landing page at `papercrane.bio`. The authenticated
 * dashboard + leaderboard live on `apps/app` at `app.papercrane.bio`. Use
 * `getAppUrl()` to link from marketing content to product surfaces (sign-in,
 * sign-up, "open app", etc.) without hardcoding hostnames.
 *
 * In production the app lives at `https://app.papercrane.bio`.
 * In local dev the app runs on `http://localhost:3002`.
 * Override either with `NEXT_PUBLIC_APP_URL`.
 */
export function getAppUrl(): string {
  const env = process.env.NEXT_PUBLIC_APP_URL;
  if (env) return env.replace(/\/$/, "");
  if (process.env.NODE_ENV === "development") return "http://localhost:3002";
  return "https://app.papercrane.bio";
}
