import { test, expect } from "@playwright/test";
import { mintSessionForEmail, injectSupabaseSession } from "./fixtures/auth";

/**
 * 01: Sign-up happy path.
 *
 * The real flow is: enter email → Supabase emails a magic link → user clicks
 * it → /auth/callback exchanges the code → middleware sees a session →
 * redirected to /onboarding.
 *
 * In test we can't poll an inbox, so we:
 *   1. Render /login and verify the form renders.
 *   2. Submit the email form (real Supabase OTP request).
 *   3. Assert the "magic-link-sent" confirmation toast appears.
 *   4. Mint the session admin-side (mintSessionForEmail) and inject cookies
 *      to simulate the user clicking the link.
 *   5. Navigate to /app: middleware should redirect a fresh user (no org)
 *      to /onboarding.
 */

const NEW_USER_EMAIL = `e2e-signup-${Date.now()}@papercrane.dev`;

test.describe("Sign-up", () => {
  test("submitting the email form shows the confirmation message", async ({
    page,
  }) => {
    await page.goto("/login");

    await expect(
      page.getByRole("heading", { name: /sign in/i })
    ).toBeVisible();

    const email = page.getByTestId("e2e-signup-email");
    await expect(email).toBeVisible();
    await email.fill(NEW_USER_EMAIL);

    const submit = page.getByTestId("e2e-signup-submit");
    await expect(submit).toBeEnabled();
    await submit.click();

    // Either the magic-link sent message OR an error pill: assert the page
    // didn't crash and the confirmation copy renders.
    await expect(
      page.getByText(/check.*for a sign-in link/i, { exact: false })
    ).toBeVisible({ timeout: 10_000 });
  });

  test("authed user is redirected to /onboarding from /app", async ({
    page,
    context,
    baseURL,
  }) => {
    test.skip(
      !process.env.SUPABASE_SERVICE_ROLE_KEY,
      "Requires SUPABASE_SERVICE_ROLE_KEY to mint a session"
    );

    // Simulate the user clicking the magic link by minting a session.
    const session = await mintSessionForEmail(NEW_USER_EMAIL);
    await injectSupabaseSession(
      context,
      baseURL ?? "http://localhost:3002",
      session
    );

    await page.goto("/app");

    // A brand-new user with no org should land on /onboarding/welcome
    // (the middleware-driven redirect chain).
    await page.waitForURL(/\/onboarding/, { timeout: 10_000 });
    await expect(page).toHaveURL(/\/onboarding/);

    await expect(
      page.getByRole("heading", { name: /welcome to paper crane/i })
    ).toBeVisible();
  });

  test("Google OAuth button is interactive", async ({ page }) => {
    await page.goto("/login");
    const google = page.getByTestId("e2e-signup-google");
    await expect(google).toBeVisible();
    await expect(google).toBeEnabled();
    // Don't click: the OAuth provider would navigate away from localhost.
  });
});
