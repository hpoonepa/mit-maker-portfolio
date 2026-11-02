import { test, expect } from "./fixtures/auth";
import type { Page } from "@playwright/test";

/**
 * 05: The standalone /app/jobs/new wizard (multi-tool "compare" flow).
 *
 * Covers two paths through the 4-step wizard (Tools → Input → Designs → Review):
 *
 *   A) Happy path / compare:
 *        2 compatible tools → target → accept Auto allocation → review → Launch
 *        → lands back on /app/jobs.
 *
 *   B) Single-tool path:
 *        1 tool → target → Designs step shows NO allocation-strategy block
 *        (allocation only appears when 2+ tools are selected).
 *
 * Auth + baseURL come from ./fixtures/auth (authedPage). jobs.submit is
 * intercepted with a tRPC-shaped 200 so the test never needs a live worker
 * (dev mode also short-circuits server-side, but the stub keeps it
 * deterministic and batch-size agnostic).
 *
 * Tooling note: the wizard talks to `trpc.tools.list`, so the available tool
 * ids depend on the seeded catalog. BindCraft and Chroma are selected
 * deliberately because both use the saved-target input kind; choosing the
 * first two cards could mix incompatible input kinds as catalog ordering
 * changes. Missing fixtures skip loudly rather than producing a false failure.
 */

const PRIMARY_NEXT = /next/i;
const PRIMARY_LAUNCH = /launch .*design/i;

/** Click the wizard's primary button (Next/Launch), waiting for it to enable. */
async function clickPrimary(page: Page, name: RegExp): Promise<void> {
  const btn = page.getByRole("button", { name });
  await expect(btn).toBeEnabled({ timeout: 10_000 });
  await btn.click();
}

/** Select one known runnable tool without depending on catalog ordering. */
async function selectTool(
  page: Page,
  query: string,
  toolId: string,
): Promise<boolean> {
  const search = page.getByRole("searchbox", { name: "Search tools" });
  await search.fill(query);
  const card = page.getByTestId(`e2e-job-tool-${toolId}`);
  if (!(await card.isVisible().catch(() => false))) return false;
  const enabled = await expect(card)
    .toBeEnabled({ timeout: 10_000 })
    .then(() => true)
    .catch(() => false);
  if (!enabled) return false;
  await card.click();
  await expect(card).toHaveAttribute("aria-checked", "true");
  return true;
}

/** Pick the first real target from the input-step dropdown. Returns false if none. */
async function selectFirstTarget(page: Page): Promise<boolean> {
  const targetSelect = page.getByTestId("e2e-job-target-select");
  if (!(await targetSelect.isVisible().catch(() => false))) return false;
  const options = targetSelect.locator("option");
  // option[0] is the disabled "Select a target…" placeholder.
  if ((await options.count()) <= 1) return false;
  const value = await options.nth(1).getAttribute("value");
  if (!value) return false;
  await targetSelect.selectOption(value);
  return true;
}

/** Stub `jobs.submit` with a batch-size-aware tRPC 200 body. */
async function stubSubmit(page: Page): Promise<void> {
  await page.route("**/api/trpc/jobs.submit**", async (route) => {
    let count = 1;
    try {
      const post = route.request().postData();
      if (post) {
        const parsed = JSON.parse(post);
        if (Array.isArray(parsed)) {
          count = parsed.length || 1;
        } else if (parsed && typeof parsed === "object") {
          // httpBatchLink shape: { "0": {...}, "1": {...} }
          count = Object.keys(parsed).length || 1;
        }
      }
    } catch {
      count = 1;
    }
    const body = Array.from({ length: count }, (_v, i) => ({
      result: {
        data: {
          json: { id: `job_e2e_${Date.now()}_${i}`, status: "preparing" },
        },
      },
    }));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

test.describe("New job wizard (/app/jobs/new)", () => {
  test("happy path: 2 tools → target → auto allocation → review → launch → /app/jobs", async ({
    authedPage: page,
  }) => {
    await stubSubmit(page);
    await page.goto("/app/jobs/new");

    await expect(page.getByTestId("e2e-job-wizard")).toBeVisible({
      timeout: 15_000,
    });

    // ── Step 0: pick 2 compatible target-based tools (compare mode) ──────────
    await expect(page.getByTestId("e2e-tool-picker")).toBeVisible({
      timeout: 10_000,
    });
    const hasBindCraft = await selectTool(page, "BindCraft", "bindcraft");
    const hasChroma = await selectTool(page, "Chroma", "chroma");
    if (!hasBindCraft || !hasChroma) {
      test.skip(
        true,
        "BindCraft and Chroma must be seeded and available for compare E2E.",
      );
      return;
    }

    // The picker's mode banner should flip to "compare" with 2 selected.
    await expect(page.getByTestId("e2e-tool-picker-mode")).toHaveAttribute(
      "data-mode",
      "compare",
    );
    await clickPrimary(page, PRIMARY_NEXT);

    // ── Step 1: select the saved target shared by both tools ──────────────────
    if (!(await selectFirstTarget(page))) {
      test.skip(true, "No targets seeded for the test user: seed first.");
      return;
    }
    await clickPrimary(page, PRIMARY_NEXT);

    // ── Step 2: designs + allocation. Accept the default Auto strategy. ───────
    const allocation = page.getByTestId("e2e-allocation-control");
    await expect(allocation).toBeVisible({ timeout: 10_000 });
    const auto = page.getByTestId("e2e-allocation-strategy-auto");
    await expect(auto).toHaveAttribute("aria-checked", "true");
    await clickPrimary(page, PRIMARY_NEXT);

    // ── Step 3: review → Launch ───────────────────────────────────────────────
    await expect(page.getByTestId("e2e-job-review")).toBeVisible({
      timeout: 10_000,
    });
    await clickPrimary(page, PRIMARY_LAUNCH);

    // handleRun() router.push("/app/jobs") on all-success.
    await page.waitForURL(/\/app\/jobs(\?.*)?$/, { timeout: 15_000 });
    await expect(page).toHaveURL(/\/app\/jobs(\?.*)?$/);
  });

  test("single-tool path: no allocation-strategy block on the Designs step", async ({
    authedPage: page,
  }) => {
    await page.goto("/app/jobs/new");
    await expect(page.getByTestId("e2e-job-wizard")).toBeVisible({
      timeout: 15_000,
    });

    // ── Step 0: pick exactly 1 target-based tool ──────────────────────────────
    await expect(page.getByTestId("e2e-tool-picker")).toBeVisible({
      timeout: 10_000,
    });
    if (!(await selectTool(page, "BindCraft", "bindcraft"))) {
      test.skip(true, "BindCraft must be seeded and available for this E2E.");
      return;
    }

    // Single selection → mode banner stays "single".
    await expect(page.getByTestId("e2e-tool-picker-mode")).toHaveAttribute(
      "data-mode",
      "single",
    );
    await clickPrimary(page, PRIMARY_NEXT);

    // ── Step 1: select a saved target ────────────────────────────────────────
    if (!(await selectFirstTarget(page))) {
      test.skip(true, "No targets seeded for the test user: seed first.");
      return;
    }
    await clickPrimary(page, PRIMARY_NEXT);

    // ── Step 2: designs. The allocation-strategy block must NOT be present. ───
    // The SeedAllocator still renders, but allocation only appears for 2+ tools.
    await expect(page.getByText(/designs & allocation/i)).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByTestId("e2e-allocation-control")).toHaveCount(0);
  });
});
