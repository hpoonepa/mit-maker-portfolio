import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getDesign: vi.fn(), accessStatus: vi.fn() }));
vi.mock("@/lib/trpc/server", () => ({
  createServerTrpc: async () => ({
    beta: { accessStatus: { query: mocks.accessStatus } },
    designs: { get: { query: mocks.getDesign } },
  }),
}));
import { GET } from "./route";

const design = {
  id: "401a9a7e-9b88-4a84-98f4-bc35d34e3163",
  seed: 103,
  metrics: { sequence: "MKT", score: 0.9876, global_score: 1.2345, seq_recovery: 0.5 },
  jobId: "6a759e29-9844-4a7c-8d8c-28bd3fc59a6e",
  tool: "proteinmpnn",
  provenance: "real",
  artifactKey: "orgs/o/jobs/j/designs/103.cif",
  structureUrl: "https://r2.example/signed.cif",
};
function download(format: string) {
  return GET(new Request(`https://app.example/api/designs/${design.id}/export/${format}`), {
    params: Promise.resolve({ id: design.id, format }),
  });
}
beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_BETA_GATE", "off");
  mocks.getDesign.mockResolvedValue(design);
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  mocks.getDesign.mockReset();
  mocks.accessStatus.mockReset();
});

describe("authenticated result export", () => {
  it("rejects unknown formats before querying a result", async () => {
    expect((await download("xml")).status).toBe(404);
    expect(mocks.getDesign).not.toHaveBeenCalled();
  });
  it("enforces beta admission before querying direct exports", async () => {
    vi.stubEnv("NEXT_PUBLIC_BETA_GATE", "on");
    mocks.accessStatus.mockResolvedValue({ granted: false });
    expect((await download("json")).status).toBe(403);
    expect(mocks.getDesign).not.toHaveBeenCalled();
  });
  it("fails closed when beta admission cannot be checked", async () => {
    vi.stubEnv("NEXT_PUBLIC_BETA_GATE", "on");
    mocks.accessStatus.mockRejectedValue(new Error("network unavailable"));
    expect((await download("json")).status).toBe(503);
    expect(mocks.getDesign).not.toHaveBeenCalled();
  });
  it("allows admitted beta users", async () => {
    vi.stubEnv("NEXT_PUBLIC_BETA_GATE", "on");
    mocks.accessStatus.mockResolvedValue({ granted: true });
    expect((await download("json")).status).toBe(200);
    expect(mocks.getDesign).toHaveBeenCalledTimes(1);
    expect(mocks.getDesign).toHaveBeenCalledWith({ id: design.id });
  });
  it.each([
    ["UNAUTHORIZED", 401],
    ["NOT_FOUND", 404],
    ["FORBIDDEN", 403],
    ["INTERNAL_SERVER_ERROR", 503],
  ])("preserves scoped lookup failure %s as HTTP %s", async (code, status) => {
    mocks.getDesign.mockRejectedValue({ data: { code }, message: "private upstream details" });
    const response = await download("json");
    expect(response.status).toBe(status);
    expect(await response.text()).not.toContain("private upstream details");
  });
  it("returns 404 for an absent result without falling back to another lookup", async () => {
    mocks.getDesign.mockResolvedValue(null);
    expect((await download("json")).status).toBe(404);
    expect(mocks.getDesign).toHaveBeenCalledTimes(1);
  });
  it("preserves recorded origin and sequence in FASTA", async () => {
    mocks.getDesign.mockResolvedValue({ ...design, provenance: "synthetic" });
    const response = await download("fasta");
    expect(response.status).toBe(200);
    expect(await response.text()).toContain("provenance=synthetic");
    expect(response.headers.get("cache-control")).toBe("private, no-store");
  });
  it("preserves native ProteinMPNN scores exactly in JSON", async () => {
    const response = await download("json");
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({
      sequence: "MKT", length: 3, tool: "proteinmpnn", provenance: "real", metrics: design.metrics,
    });
  });
  it("exports native ProteinMPNN scores in named CSV columns", async () => {
    const response = await download("csv");
    const [header = [], values = []] = (await response.text()).trim().split("\n").map(line => line.split(","));
    const record = Object.fromEntries(header.map((key, index) => [key, values[index]]));
    expect(record).toMatchObject({ sequence: "MKT", tool: "proteinmpnn", provenance: "real", score: "0.9876", global_score: "1.2345", seq_recovery: "0.5" });
    expect(header).not.toContain("ipTM");
  });
  it("exports unknown provenance explicitly", async () => {
    mocks.getDesign.mockResolvedValue({ ...design, provenance: undefined });
    expect(await (await download("json")).json()).toMatchObject({ provenance: "unknown" });
    expect(await (await download("csv")).text()).toContain("unknown");
  });
  it("refuses an empty FASTA when no sequence was recorded", async () => {
    mocks.getDesign.mockResolvedValue({ ...design, metrics: {} });
    expect((await download("fasta")).status).toBe(409);
  });
  it("streams actual CIF bytes using one scoped lookup", async () => {
    const content = "data_model\n_atom_site.id 1\n";
    const fetchMock = vi.fn().mockResolvedValue(new Response(content));
    vi.stubGlobal("fetch", fetchMock);
    const response = await download("cif");
    expect(response.status).toBe(200);
    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("content-type")).toContain("chemical/x-cif");
    expect(await response.text()).toBe(content);
    expect(mocks.getDesign).toHaveBeenCalledTimes(1);
    expect(mocks.getDesign).toHaveBeenCalledWith({ id: design.id });
    expect(fetchMock).toHaveBeenCalledWith(design.structureUrl, { cache: "no-store" });
  });
  it.each([
    ["pdb", "data_model\n_atom_site.id 1\n", "cif"],
    ["cif", "HEADER    TEST\nATOM      1\n", "pdb"],
    ["cif", "not a structure", null],
  ])("refuses to mislabel stored bytes as %s", async (format, content, actualFormat) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(content)));
    const response = await download(format);
    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({ availableFormat: actualFormat });
  });
  it("returns a gateway error when R2 fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("expired", { status: 403 })));
    const response = await download("cif");
    expect(response.status).toBe(502);
    expect(response.headers.get("x-papercrane-placeholder")).toBeNull();
  });
  it("never returns a successful structure download without a stored artifact", async () => {
    mocks.getDesign.mockResolvedValue({ ...design, artifactKey: null, structureUrl: null });
    const response = await download("cif");
    expect(response.status).toBe(409);
    expect(await response.text()).toContain("NO ATOMIC COORDINATES");
  });
});
