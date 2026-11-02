import { describe, expect, it, vi } from "vitest";
import {
  fetchTargetStructure,
  targetStructureSources,
} from "./fetchTargetStructure";

describe("targetStructureSources", () => {
  it("prefers an uploaded structure and keeps RCSB as a fallback", () => {
    expect(
      targetStructureSources("https://r2.example/missing.pdb", "5mv5"),
    ).toEqual([
      { url: "https://r2.example/missing.pdb", label: "uploaded structure" },
      { url: "/api/pdb/5MV5?format=auto", label: "RCSB" },
    ]);
  });
});

describe("fetchTargetStructure", () => {
  it("falls back to RCSB when the stored upload no longer exists", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response("missing", { status: 404 }))
      .mockResolvedValueOnce(new Response("data_5MV5\n#", { status: 200 }));

    const text = await fetchTargetStructure(
      targetStructureSources("https://r2.example/missing.pdb", "5MV5"),
      undefined,
      fetchImpl,
    );

    expect(text).toContain("data_5MV5");
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("surfaces the final source error when every source fails", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response("missing", { status: 404 }),
    );

    await expect(
      fetchTargetStructure(
        targetStructureSources("https://r2.example/missing.pdb", "5MV5"),
        undefined,
        fetchImpl,
      ),
    ).rejects.toThrow(/RCSB returned 404/);
  });
});
