/**
 * Cross-deployment link helpers.
 *
 * `apps/app` serves the authenticated dashboard + public leaderboard at
 * `app.papercrane.bio`. Any link back to the landing page must cross the
 * origin boundary. Use `getWebUrl()` to build those links.
 *
 * In production the landing lives at `https://papercrane.bio`.
 * In local dev the landing runs on `http://localhost:3000`.
 * Override either with `NEXT_PUBLIC_WEB_URL`.
 */
export function getWebUrl(): string {
  const env = process.env.NEXT_PUBLIC_WEB_URL;
  if (env) return env.replace(/\/$/, "");
  if (process.env.NODE_ENV === "development") return "http://localhost:3000";
  return "https://papercrane.bio";
}
