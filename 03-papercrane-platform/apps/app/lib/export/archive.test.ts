// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { strFromU8, unzipSync } from "fflate";
import { buildResearchArchive, collectArchiveDesigns } from "./archive";

describe("research archive integrity", () => {
  it("exports the 501st record with independent files and an auditable manifest", async () => {
    const designs = Array.from({ length: 501 }, (_, i) => ({ id: `design-${i}`, seed: i }));
    const fetchPage = vi.fn(async (cursor?: string) => cursor
      ? { items: designs.slice(500), nextCursor: null }
      : { items: designs.slice(0, 500), nextCursor: "page-2" });
    const all = await collectArchiveDesigns(fetchPage);
    const result = await buildResearchArchive({
      designs: all, formats: ["json"], scope: "job", scopeId: "job-1",
      snapshotAt: "2026-09-08T12:00:00.000Z",
      request: vi.fn(async () => new Response('{"value":1}')),
    });
    const files = unzipSync(result.bytes);
    expect(all).toHaveLength(501);
    expect(JSON.parse(strFromU8(files["designs/design-500.json"]!))).toEqual({ value: 1 });
    expect(Object.keys(files)).toHaveLength(502);
    expect(JSON.parse(strFromU8(files["manifest.json"]!))).toMatchObject({
      complete: true, completeDesigns: 501, exportedFiles: 501, failedFiles: 0,
    });
    expect(result.manifest.files[0]).toMatchObject({ provenance: "unknown", status: "exported" });
    expect(result.manifest.files[0]).toHaveProperty("sha256", expect.stringMatching(/^[a-f0-9]{64}$/));
  });

  it("records HTTP failures, network failures, and empty files without claiming completion", async () => {
    const result = await buildResearchArchive({
      designs: [{ id: "d1", seed: 1, provenance: "stub" }],
      formats: ["json", "cif", "csv", "fasta"], scope: "project", scopeId: "p1",
      snapshotAt: "2026-09-08T12:00:00.000Z",
      request: vi.fn()
        .mockResolvedValueOnce(new Response('{}'))
        .mockResolvedValueOnce(new Response("missing", { status: 404 }))
        .mockRejectedValueOnce(new Error("Network unavailable"))
        .mockResolvedValueOnce(new Response("")),
    });
    expect(result.manifest).toMatchObject({ complete: false, completeDesigns: 0, exportedFiles: 1, failedFiles: 3, requestedFiles: 4 });
    expect(Object.keys(unzipSync(result.bytes))).toEqual(["designs/d1.json", "manifest.json"]);
    expect(result.manifest.files.every((file) => file.provenance === "stub")).toBe(true);
  });

  it("refuses broken pagination instead of returning a partial collection", async () => {
    await expect(collectArchiveDesigns(async () => ({ items: [], nextCursor: "same" }))).rejects.toThrow(/stopped advancing/);
    const fetchPage = vi.fn().mockResolvedValueOnce({ items: [{ id: "d1", seed: 1 }], nextCursor: "next" }).mockRejectedValueOnce(new Error("API unavailable"));
    await expect(collectArchiveDesigns(fetchPage)).rejects.toThrow("API unavailable");
  });
});
