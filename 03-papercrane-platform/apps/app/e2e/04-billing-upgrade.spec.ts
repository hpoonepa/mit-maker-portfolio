import { test, expect } from "./fixtures/auth";

/**
 * 04: Free-tier user sees the Upgrade CTA and Stripe Checkout opens in
 * test mode.
 *
 * The seeded Supabase test user is on the Free tier by default, so the
 * billing page renders <UpgradeCTA variant="card" /> below the current-plan
 * card. Clicking it opens the UpgradeModal; clicking Subscribe inside that
 * triggers a POST to `/v1/billing/checkout` which returns a Stripe Checkout
 * URL the client navigates to.
 *
 * In tests we intercept the checkout endpoint so we can:
 *   - confirm the request shape (priceId, returnPath) without hitting Stripe
 *   - return a deterministic redirect URL (test-mode `cs_test_…`)
 *   - assert the browser actually navigates there
 *
 * We then stop the navigation at the Stripe domain (Playwright `route.abort`)
 * so the test stays self-contained.
 */

const STRIPE_TEST_CHECKOUT_URL =
  "https://checkout.stripe.com/c/pay/cs_test_e2e_papercrane_pro_monthly";

test.describe("Billing: Free → Upgrade CTA → Stripe Checkout", () => {
  test("Free-tier user sees the upgrade card on /settings/billing", async ({
    authedPage: page,
  }) => {
    await page.goto("/settings/billing");

    await expect(
      page.getByRole("heading", { name: /plan.*invoices/i })
    ).toBeVisible();

    // Free tier renders the variant="card" CTA.
    const cta = page.getByTestId("e2e-upgrade-cta").first();
    await expect(cta).toBeVisible({ timeout: 10_000 });
    await expect(cta).toContainText(/upgrade/i);
  });

  test("clicking the CTA opens the upgrade modal", async ({
    authedPage: page,
  }) => {
    await page.goto("/settings/billing");

    const cta = page.getByTestId("e2e-upgrade-cta").first();
    await cta.click();

    const modal = page.getByTestId("e2e-upgrade-modal");
    await expect(modal).toBeVisible();
    await expect(
      modal.getByRole("heading", { name: /pro/i })
    ).toBeVisible();
  });

  test("Subscribe button opens Stripe Checkout in test mode", async ({
    authedPage: page,
  }) => {
    // Intercept the billing checkout endpoint so we control the redirect URL.
    let capturedBody: unknown = null;
    await page.route("**/v1/billing/checkout", async (route) => {
      capturedBody = await route.request().postDataJSON().catch(() => null);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ url: STRIPE_TEST_CHECKOUT_URL }),
      });
    });

    // Block the actual Stripe navigation: we just want to verify the
    // browser was asked to navigate there.
    let stripeNavigated = false;
    await page.route("https://checkout.stripe.com/**", (route) => {
      stripeNavigated = true;
      // Returning a tiny body keeps Playwright from waiting forever; we
      // explicitly do NOT actually load Stripe in CI.
      return route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<html><body>stripe-test-stub</body></html>",
      });
    });

    await page.goto("/settings/billing");
    await page.getByTestId("e2e-upgrade-cta").first().click();

    const modal = page.getByTestId("e2e-upgrade-modal");
    await expect(modal).toBeVisible();

    const subscribe = page.getByTestId("e2e-upgrade-subscribe");
    await expect(subscribe).toBeEnabled();

    // Click + wait for the Stripe URL to be reached (or our stub to fulfil).
    await Promise.all([
      page.waitForURL(/checkout\.stripe\.com|stripe-test-stub/i, {
        timeout: 15_000,
      }),
      subscribe.click(),
    ]);

    expect(stripeNavigated).toBe(true);
    // The checkout call should have included a priceId and a returnPath.
    expect(capturedBody).toMatchObject({
      priceId: expect.any(String),
      returnPath: expect.stringContaining("/settings/billing"),
    });
  });

  test("Pro-tier user does NOT see the upgrade CTA (smoke)", async ({
    authedPage: page,
  }) => {
    // Stub the subscription query to flip the user to Pro for this test.
    await page.route("**/api/trpc/billing.currentSubscription**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          { result: { data: { json: { tier: "pro", isFree: false } } } },
        ]),
      })
    );

    await page.goto("/settings/billing");
    await expect(page.getByTestId("e2e-upgrade-cta")).toHaveCount(0);
  });
});
