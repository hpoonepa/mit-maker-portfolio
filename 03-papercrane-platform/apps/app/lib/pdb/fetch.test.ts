/**
 * Unit tests for the hardened RCSB PDB fetch helpers.
 *
 * We mock `globalThis.fetch` rather than hitting the real RCSB CDN so the
 * suite stays deterministic and offline-friendly. Each `it()` clears the
 * sessionStorage probe cache to keep cases independent.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  PdbFetchError,
  _clearPdbCache,
  headFetchPdb,
  pdbCdnUrl,
  validatePdbId,
} from "./fetch";

type FetchMock = ReturnType<typeof vi.fn>;

function makeRes(status: number): Response {
  return new Response(null, { status });
}

beforeEach(() => {
  _clearPdbCache();
});

afterEach(() => {
  vi.restoreAllMocks();
  _clearPdbCache();
});

describe("validatePdbId", () => {
  it("uppercases valid 4-char IDs", () => {
    expect(validatePdbId("6x1a")).toBe("6X1A");
    expect(validatePdbId("1CRN")).toBe("1CRN");
    expect(validatePdbId("4HHB")).toBe("4HHB");
  });

  it("rejects garbage with PdbFetchError(invalid_id)", () => {
    expect(() => validatePdbId("XYZ1")).toThrow(PdbFetchError);
    expect(() => validatePdbId("")).toThrow(PdbFetchError);
    try {
      validatePdbId("XYZ1");
    } catch (e) {
      expect((e as PdbFetchError).code).toBe("invalid_id");
    }
  });
});

describe("pdbCdnUrl", () => {
  it("builds proxy URLs", () => {
    expect(pdbCdnUrl("6X1A").url).toBe("/api/pdb/6X1A?format=cif");
    expect(pdbCdnUrl("6X1A", "pdb").url).toBe("/api/pdb/6X1A?format=pdb");
  });
});

describe("headFetchPdb", () => {
  it("returns the .cif URL on a 200 response", async () => {
    const fetchMock: FetchMock = vi.fn().mockResolvedValue(makeRes(200));
    vi.stubGlobal("fetch", fetchMock);

    const result = await headFetchPdb("6X1A");
    expect(result.format).toBe("cif");
    expect(result.url).toBe("/api/pdb/6X1A?format=cif");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("falls back from .cif → .pdb on 404", async () => {
    const fetchMock: FetchMock = vi
      .fn()
      .mockResolvedValueOnce(makeRes(404)) // cif
      .mockResolvedValueOnce(makeRes(200)); // pdb
    vi.stubGlobal("fetch", fetchMock);

    const result = await headFetchPdb("1CRN", "auto");
    expect(result.format).toBe("pdb");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("retries 5xx with backoff and eventually succeeds", async () => {
    const fetchMock: FetchMock = vi
      .fn()
      .mockResolvedValueOnce(makeRes(503))
      .mockResolvedValueOnce(makeRes(502))
      .mockResolvedValueOnce(makeRes(200));
    vi.stubGlobal("fetch", fetchMock);

    const result = await headFetchPdb("6X1A");
    expect(result.url).toBe("/api/pdb/6X1A?format=cif");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  }, 10_000);

  it("surfaces 'PDB ID not found' when both formats 404", async () => {
    const fetchMock: FetchMock = vi
      .fn()
      .mockResolvedValue(makeRes(404));
    vi.stubGlobal("fetch", fetchMock);

    await expect(headFetchPdb("9ZZZ")).rejects.toMatchObject({
      code: "not_found",
      message: expect.stringContaining("not found"),
    });
  });

  it("surfaces 'RCSB unavailable' after 5xx exhausts retries", async () => {
    const fetchMock: FetchMock = vi
      .fn()
      .mockResolvedValue(makeRes(503));
    vi.stubGlobal("fetch", fetchMock);

    await expect(headFetchPdb("6X1A", "cif")).rejects.toMatchObject({
      code: "unavailable",
      message: expect.stringContaining("unavailable"),
    });
  }, 10_000);

  it("surfaces 'Network error' on fetch reject", async () => {
    const fetchMock: FetchMock = vi
      .fn()
      .mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(headFetchPdb("6X1A", "cif")).rejects.toMatchObject({
      code: "network",
    });
  }, 10_000);

  it("rejects invalid IDs without hitting the network", async () => {
    const fetchMock: FetchMock = vi.fn().mockResolvedValue(makeRes(200));
    vi.stubGlobal("fetch", fetchMock);

    await expect(headFetchPdb("XYZ1")).rejects.toMatchObject({
      code: "invalid_id",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("caches successful probes in sessionStorage", async () => {
    const fetchMock: FetchMock = vi.fn().mockResolvedValue(makeRes(200));
    vi.stubGlobal("fetch", fetchMock);

    await headFetchPdb("6X1A");
    await headFetchPdb("6X1A");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
