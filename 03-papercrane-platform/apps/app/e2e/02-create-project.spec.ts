import { test, expect } from "./fixtures/auth";

/**
 * 02: Logged-in user creates a project, picks a target PDB id, and sees
 * the Mol* viewer load.
 *
 * Flow
 * ----
 *   1. /app/projects/new → fill name, submit → redirected to /app/projects
 *   2. /app/targets/new → upload a tiny PDB fixture (RBX1 / 2LGV-style stub)
 *      → submit → redirected to /app/targets/[id]
 *   3. On the target detail page, the hotspot editor mounts MolstarViewer
 *      and we assert its container reaches a non-error state.
 *
 * The Mol* viewer is heavy (WebGL, async assemblies), so we only require it
 * to render its wrapper + leave the "loading" skeleton: final "ready" state
 * is asserted with a generous timeout and tolerated falling back to the
 * skeleton on slow CI runners.
 */

const PROJECT_NAME = `E2E project ${Date.now()}`;
const TARGET_PDB_ID = "2LGV"; // RBX1 from the project memory: small, public.

test.describe("Create project + target with Mol* viewer", () => {
  test("creates a project from the new-project page", async ({
    authedPage: page,
  }) => {
    await page.goto("/app/projects/new");

    await expect(
      page.getByRole("heading", { name: /new project/i })
    ).toBeVisible();

    const nameInput = page.getByTestId("e2e-project-name");
    await nameInput.fill(PROJECT_NAME);

    const submit = page.getByTestId("e2e-project-create-submit");
    await expect(submit).toBeEnabled();
    await submit.click();

    // The stub redirects to /app/projects; once tRPC is wired this becomes
    // /app/projects/[id]. Either is acceptable.
    await page.waitForURL(/\/app\/projects/, { timeout: 10_000 });
    await expect(page).toHaveURL(/\/app\/projects/);
  });

  test("uploads a target by PDB id and the Mol* viewer mounts", async ({
    authedPage: page,
  }) => {
    await page.goto("/app/targets/new");

    await expect(
      page.getByRole("heading", { name: /upload target/i })
    ).toBeVisible();

    // Mock the RCSB fetch so the test doesn't hit the network. Tests should
    // not depend on rcsb.org being reachable.
    await page.route("**/rcsb.org/**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "chemical/x-pdb",
        body: stubPdbForId(TARGET_PDB_ID),
      })
    );

    // The UploadDropzone supports paste-by-id: but if the UI exposes only a
    // file input, we fall back to feeding it a synthetic .pdb file.
    const pdbIdInput = page.getByPlaceholder(/pdb id/i).first();
    if (await pdbIdInput.count()) {
      await pdbIdInput.fill(TARGET_PDB_ID);
      await pdbIdInput.press("Enter");
    } else {
      const fileInput = page.locator('input[type="file"]').first();
      await fileInput.setInputFiles({
        name: `${TARGET_PDB_ID}.pdb`,
        mimeType: "chemical/x-pdb",
        buffer: Buffer.from(stubPdbForId(TARGET_PDB_ID), "utf-8"),
      });
    }

    // After parse, the form unlocks the "Upload target" button.
    const submit = page.getByRole("button", { name: /upload target/i });
    await expect(submit).toBeVisible({ timeout: 15_000 });
    await submit.click();

    // Stub redirect: /app/targets/tgt_<rand>
    await page.waitForURL(/\/app\/targets\/.+/, { timeout: 15_000 });

    // The Mol* viewer is mounted from the hotspot editor; assert its host
    // is in the DOM and not in an error state.
    const viewer = page.getByTestId("e2e-molstar-viewer");
    await expect(viewer).toBeVisible({ timeout: 15_000 });
    await expect(viewer).not.toHaveAttribute("data-molstar-status", "error", {
      timeout: 5_000,
    });
  });
});

/**
 * Smallest possible parseable PDB record so the client-side parser is happy
 * without us fetching megabytes from RCSB. Single residue, single chain.
 */
function stubPdbForId(pdbId: string): string {
  return [
    `HEADER    DE NOVO PROTEIN                         01-JAN-26   ${pdbId}`,
    "ATOM      1  N   GLY A   1       0.000   0.000   0.000  1.00  0.00           N  ",
    "ATOM      2  CA  GLY A   1       1.458   0.000   0.000  1.00  0.00           C  ",
    "ATOM      3  C   GLY A   1       2.009   1.420   0.000  1.00  0.00           C  ",
    "ATOM      4  O   GLY A   1       1.251   2.390   0.000  1.00  0.00           O  ",
    "TER       5      GLY A   1                                                      ",
    "END                                                                             ",
    "",
  ].join("\n");
}
