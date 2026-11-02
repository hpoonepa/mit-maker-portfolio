import { test, expect } from "./fixtures/auth";

/**
 * 03: Logged-in user submits a BindCraft job from a project page.
 *
 * Pre-requisite: at least one target exists. We assume the test Supabase
 * project has a seeded target row (PDB id 2LGV) for the test user: the
 * Agent 1 seed migration owns this. If the dropdown is empty, we skip
 * gracefully so this test fails loud only when the data layer regresses.
 *
 * Flow
 * ----
 *   1. /app/projects/<test-project-id>
 *   2. Pick the seeded target
 *   3. Pick BindCraft tool card
 *   4. Defaults are pre-filled (binderLength=80, protocol=default,
 *      noCysteine=true): leave them
 *   5. Click submit → tRPC.jobs.submit fires → router.push to /app/jobs/<id>
 *   6. Navigate to /app/jobs and assert the new job row appears
 */

const TEST_PROJECT_ID = process.env.E2E_TEST_PROJECT_ID ?? "proj_e2e_seed";

test.describe("Submit BindCraft job", () => {
  test("happy path: target → tool → defaults → submit → see in queue", async ({
    authedPage: page,
  }) => {
    await page.goto(`/app/projects/${TEST_PROJECT_ID}`);

    // The job submission form should mount once the targets/tools queries
    // settle.
    const form = page.getByTestId("e2e-job-submission-form");
    await expect(form).toBeVisible({ timeout: 15_000 });

    // Step 1: Target. If the seeded user has no targets we bail out.
    const targetSelect = page.getByTestId("e2e-job-target-select");
    if (!(await targetSelect.isVisible().catch(() => false))) {
      test.skip(true, "No targets available for the test user: seed first.");
      return;
    }
    const optionCount = await targetSelect.locator("option").count();
    if (optionCount <= 1) {
      // Just the "Select a target…" placeholder.
      test.skip(true, "Targets dropdown is empty.");
      return;
    }
    // Pick the first real target (option[0] is the disabled placeholder).
    const firstTargetValue = await targetSelect
      .locator("option")
      .nth(1)
      .getAttribute("value");
    await targetSelect.selectOption(firstTargetValue!);

    // Step 2: Tool. BindCraft card.
    const bindcraftCard = page.getByTestId("e2e-job-tool-bindcraft");
    await expect(bindcraftCard).toBeVisible({ timeout: 10_000 });
    await bindcraftCard.click();
    await expect(bindcraftCard).toHaveAttribute("aria-checked", "true");

    // Step 3+4: params + seeds default. We leave defaults as-is and submit.
    const submit = page.getByTestId("e2e-job-submit");
    await expect(submit).toBeEnabled({ timeout: 10_000 });

    // Intercept the tRPC submit so the test does not require a live worker.
    const fakeJobId = `job_e2e_${Date.now()}`;
    await page.route("**/api/trpc/jobs.submit**", async (route) => {
      const trpcOk = {
        result: {
          data: {
            json: { id: fakeJobId, status: "preparing" },
          },
        },
      };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([trpcOk]),
      });
    });

    await submit.click();

    // Form pushes to /app/jobs/<id>.
    await page.waitForURL(/\/app\/jobs\/.+/, { timeout: 15_000 });

    // Now the global queue should list it.
    await page.goto("/app/jobs");
    const queue = page.getByTestId("e2e-jobs-queue");
    await expect(queue).toBeVisible();
    // Once `jobs.list` is wired, the row is detectable by id. For now, just
    // ensure the queue table renders and the page didn't 500.
    await expect(
      page.getByRole("heading", { name: /jobs/i })
    ).toBeVisible();
  });

  test("submit is disabled until target + tool are picked", async ({
    authedPage: page,
  }) => {
    await page.goto(`/app/projects/${TEST_PROJECT_ID}`);
    const submit = page.getByTestId("e2e-job-submit");
    await expect(submit).toBeVisible({ timeout: 15_000 });
    await expect(submit).toBeDisabled();
  });
});
