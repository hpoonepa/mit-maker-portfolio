import { test as base, type Page, type BrowserContext } from "@playwright/test";

/**
 * Auth fixture: signs a Playwright browser context in as a Supabase service-role
 * test user.
 *
 * Strategy
 * --------
 * We bypass the email-OTP / Google OAuth flows in tests by minting a session
 * server-side using the Supabase admin API (service-role JWT), then injecting
 * the resulting Supabase auth cookies into Playwright's browser context.
 *
 * This requires three env vars (set in `.env.local` or CI secrets):
 *   - NEXT_PUBLIC_SUPABASE_URL         : same one the app uses
 *   - SUPABASE_SERVICE_ROLE_KEY        : service-role JWT (NEVER ship to client)
 *   - E2E_TEST_USER_EMAIL              : pre-seeded test user, e.g. e2e@papercrane.dev
 *
 * If any are missing we fail fast with a helpful message rather than running
 * the test against a broken auth state.
 *
 * Notes
 * -----
 * - We use Supabase's `admin.generateLink({ type: "magiclink" })` to get a
 *   short-lived `hashed_token`, then exchange it via `verifyOtp` so the test
 *   user lands in the same flow a real magic-link click would. The resulting
 *   session is what we drop into cookies.
 * - The `onboardingComplete` flag below is faked via a `localStorage` write so
 *   tests that depend on a logged-in *and onboarded* user don't have to walk
 *   through the entire 4-step onboarding flow.
 */

export type AuthFixtures = {
  authedPage: Page;
  authedContext: BrowserContext;
  signInAs: (email?: string) => Promise<void>;
};

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SERVICE_ROLE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;
const TEST_EMAIL =
  process.env.E2E_TEST_USER_EMAIL ?? "e2e+playwright@papercrane.dev";

function requireEnv(): { url: string; serviceKey: string } {
  if (!SUPABASE_URL || !SERVICE_ROLE_KEY) {
    throw new Error(
      "[e2e/fixtures/auth] Missing Supabase env. Set NEXT_PUBLIC_SUPABASE_URL " +
        "and SUPABASE_SERVICE_ROLE_KEY before running e2e tests."
    );
  }
  return { url: SUPABASE_URL, serviceKey: SERVICE_ROLE_KEY };
}

/**
 * Mint an access/refresh token for the given email by:
 *  1. POST /auth/v1/admin/generate_link  → { hashed_token }
 *  2. POST /auth/v1/verify              → { access_token, refresh_token, user }
 *
 * Returns a Supabase session payload we can stuff into cookies.
 */
export async function mintSessionForEmail(email: string): Promise<{
  access_token: string;
  refresh_token: string;
  user: { id: string; email: string };
}> {
  const { url, serviceKey } = requireEnv();

  const linkResp = await fetch(`${url}/auth/v1/admin/generate_link`, {
    method: "POST",
    headers: {
      apikey: serviceKey,
      Authorization: `Bearer ${serviceKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ type: "magiclink", email }),
  });

  if (!linkResp.ok) {
    const text = await linkResp.text();
    throw new Error(`generate_link failed (${linkResp.status}): ${text}`);
  }
  const link = (await linkResp.json()) as {
    properties: { hashed_token: string };
  };

  const verifyResp = await fetch(`${url}/auth/v1/verify`, {
    method: "POST",
    headers: {
      apikey: serviceKey,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      type: "magiclink",
      token: link.properties.hashed_token,
      email,
    }),
  });

  if (!verifyResp.ok) {
    const text = await verifyResp.text();
    throw new Error(`verifyOtp failed (${verifyResp.status}): ${text}`);
  }

  return (await verifyResp.json()) as {
    access_token: string;
    refresh_token: string;
    user: { id: string; email: string };
  };
}

/**
 * Inject a Supabase session into Playwright's browser context.
 *
 * The `@supabase/ssr` client reads the session from a single cookie named
 * `sb-<project-ref>-auth-token`. We compute the project ref from the URL host
 * (e.g. `https://abcd.supabase.co` → `abcd`) and serialise the session in the
 * shape Supabase expects.
 */
export async function injectSupabaseSession(
  context: BrowserContext,
  baseUrl: string,
  session: Awaited<ReturnType<typeof mintSessionForEmail>>
): Promise<void> {
  const { url } = requireEnv();
  const ref = new URL(url).hostname.split(".")[0];
  const cookieName = `sb-${ref}-auth-token`;

  const value = encodeURIComponent(
    JSON.stringify({
      access_token: session.access_token,
      refresh_token: session.refresh_token,
      expires_in: 3600,
      token_type: "bearer",
      user: session.user,
    })
  );

  const target = new URL(baseUrl);
  await context.addCookies([
    {
      name: cookieName,
      value,
      domain: target.hostname,
      path: "/",
      httpOnly: false,
      secure: target.protocol === "https:",
      sameSite: "Lax",
    },
  ]);
}

/**
 * Extended Playwright `test` with an auto-signed-in `authedPage` fixture.
 *
 *   import { test, expect } from "@/e2e/fixtures/auth";
 *
 *   test("only logged-in users see /app", async ({ authedPage }) => {
 *     await authedPage.goto("/app");
 *     await expect(authedPage).toHaveURL(/\/app/);
 *   });
 */
export const test = base.extend<AuthFixtures>({
  authedContext: async ({ context, baseURL }, use) => {
    const session = await mintSessionForEmail(TEST_EMAIL);
    await injectSupabaseSession(context, baseURL ?? "http://localhost:3002", session);
    await use(context);
  },

  authedPage: async ({ authedContext }, use) => {
    const page = await authedContext.newPage();
    // Mark onboarding as complete so the dashboard pages render directly.
    await page.addInitScript(() => {
      try {
        window.localStorage.setItem("papercrane.onboarding.complete", "true");
      } catch {
        /* no-op for non-DOM contexts */
      }
    });
    await use(page);
    await page.close();
  },

  signInAs: async ({ context, baseURL }, use) => {
    await use(async (email = TEST_EMAIL) => {
      const session = await mintSessionForEmail(email);
      await injectSupabaseSession(context, baseURL ?? "http://localhost:3002", session);
    });
  },
});

export { expect } from "@playwright/test";
