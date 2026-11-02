import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Presign contract:
 * - `presignGet(handle, key, ttl?)` signs a GET with expiresIn = ttl (default 900s)
 * - `presignPut(handle, key, contentType, contentLength?, ttl?)` signs a PUT
 *   and binds `content-type` (+ `content-length` if provided) into the signature
 * - Invalid TTL / empty key throws before the signer is touched
 */

// Capture args passed to getSignedUrl for inspection.
const getSignedUrl = vi.fn();
vi.mock("@aws-sdk/s3-request-presigner", () => ({
  getSignedUrl: (...args: unknown[]) => getSignedUrl(...args),
}));

// Stub the S3 command constructors so we can inspect inputs.
vi.mock("@aws-sdk/client-s3", () => ({
  S3Client: vi.fn(),
  GetObjectCommand: vi.fn().mockImplementation((input: unknown) => ({
    __type: "GetObjectCommand",
    input,
  })),
  PutObjectCommand: vi.fn().mockImplementation((input: unknown) => ({
    __type: "PutObjectCommand",
    input,
  })),
}));

const fakeHandle = {
  client: { __s3: true } as unknown as never,
  bucket: "papercrane-prod",
  endpoint: "https://acct.r2.cloudflarestorage.com",
};

describe("presignGet", () => {
  beforeEach(() => {
    getSignedUrl.mockReset();
    getSignedUrl.mockResolvedValue("https://signed.example/get");
  });

  it("signs a GET with default TTL of 15 minutes", async () => {
    const { presignGet, DEFAULT_PRESIGN_TTL_SEC } = await import(
      "../src/presign"
    );
    expect(DEFAULT_PRESIGN_TTL_SEC).toBe(900);

    const url = await presignGet(fakeHandle, "orgs/o/targets/t/input.pdb");
    expect(url).toBe("https://signed.example/get");

    expect(getSignedUrl).toHaveBeenCalledTimes(1);
    const [, command, opts] = getSignedUrl.mock.calls[0]!;
    expect(command.__type).toBe("GetObjectCommand");
    expect(command.input).toEqual({
      Bucket: "papercrane-prod",
      Key: "orgs/o/targets/t/input.pdb",
    });
    expect(opts).toEqual({ expiresIn: 900 });
  });

  it("honours caller-supplied TTL", async () => {
    const { presignGet } = await import("../src/presign");
    await presignGet(fakeHandle, "k", 60);
    const [, , opts] = getSignedUrl.mock.calls[0]!;
    expect(opts.expiresIn).toBe(60);
  });

  it("rejects empty key before signing", async () => {
    const { presignGet } = await import("../src/presign");
    await expect(presignGet(fakeHandle, "")).rejects.toThrow(/key/);
    expect(getSignedUrl).not.toHaveBeenCalled();
  });

  it("rejects non-positive TTL", async () => {
    const { presignGet } = await import("../src/presign");
    await expect(presignGet(fakeHandle, "k", 0)).rejects.toThrow(/ttlSec/);
    await expect(presignGet(fakeHandle, "k", -1)).rejects.toThrow(/ttlSec/);
  });

  it("rejects TTL above SigV4 7-day cap", async () => {
    const { presignGet } = await import("../src/presign");
    await expect(
      presignGet(fakeHandle, "k", 7 * 24 * 60 * 60 + 1),
    ).rejects.toThrow(/SigV4/);
  });
});

describe("presignPut", () => {
  beforeEach(() => {
    getSignedUrl.mockReset();
    getSignedUrl.mockResolvedValue("https://signed.example/put");
  });

  it("signs a PUT with content-type bound into the signature", async () => {
    const { presignPut } = await import("../src/presign");
    const url = await presignPut(fakeHandle, "orgs/o/up.pdb", "chemical/x-pdb");
    expect(url).toBe("https://signed.example/put");

    const [, command, opts] = getSignedUrl.mock.calls[0]!;
    expect(command.__type).toBe("PutObjectCommand");
    expect(command.input).toEqual({
      Bucket: "papercrane-prod",
      Key: "orgs/o/up.pdb",
      ContentType: "chemical/x-pdb",
    });
    expect(opts.expiresIn).toBe(900);
    // signableHeaders is a Set<string>
    expect(opts.signableHeaders).toBeInstanceOf(Set);
    expect(opts.signableHeaders.has("content-type")).toBe(true);
    expect(opts.signableHeaders.has("content-length")).toBe(false);
  });

  it("adds content-length to both command input and signable headers when provided", async () => {
    const { presignPut } = await import("../src/presign");
    await presignPut(fakeHandle, "k", "application/octet-stream", 12345);

    const [, command, opts] = getSignedUrl.mock.calls[0]!;
    expect(command.input.ContentLength).toBe(12345);
    expect(opts.signableHeaders.has("content-length")).toBe(true);
  });

  it("honours caller-supplied TTL", async () => {
    const { presignPut } = await import("../src/presign");
    await presignPut(fakeHandle, "k", "text/plain", undefined, 60);
    const [, , opts] = getSignedUrl.mock.calls[0]!;
    expect(opts.expiresIn).toBe(60);
  });

  it("rejects empty key", async () => {
    const { presignPut } = await import("../src/presign");
    await expect(presignPut(fakeHandle, "", "text/plain")).rejects.toThrow(
      /key/,
    );
    expect(getSignedUrl).not.toHaveBeenCalled();
  });

  it("rejects empty content type", async () => {
    const { presignPut } = await import("../src/presign");
    await expect(presignPut(fakeHandle, "k", "")).rejects.toThrow(
      /contentType/,
    );
  });

  it("rejects non-integer / negative content length", async () => {
    const { presignPut } = await import("../src/presign");
    await expect(presignPut(fakeHandle, "k", "text/plain", -1)).rejects.toThrow(
      /contentLength/,
    );
    await expect(
      presignPut(fakeHandle, "k", "text/plain", 1.5),
    ).rejects.toThrow(/contentLength/);
  });
});
