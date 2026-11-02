import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchStructureText } from "./useMolstar";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchStructureText", () => {
  it("returns non-empty structure text from a successful response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("data_model\n_atom_site.id 1\n", { status: 200 }),
      ),
    );

    await expect(fetchStructureText("/api/designs/d1/export/cif")).resolves.toContain(
      "data_model",
    );
  });

  it("surfaces the HTTP status before Molstar creates an invalid data cell", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("expired", { status: 403, statusText: "Forbidden" }),
      ),
    );

    await expect(
      fetchStructureText("/api/designs/d1/export/cif"),
    ).rejects.toThrow("Structure request failed (403 Forbidden)");
  });

  it("rejects an empty structure response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("  \n", { status: 200 })),
    );

    await expect(
      fetchStructureText("/api/designs/d1/export/cif"),
    ).rejects.toThrow("Structure response was empty");
  });
});
