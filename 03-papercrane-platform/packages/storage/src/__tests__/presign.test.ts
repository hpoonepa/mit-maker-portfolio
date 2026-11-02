import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Presign tests focused on Wave 8 acceptance criteria:
 * - PUT URLs carry correct expiry, content-type, and (when provided) max-size
 * - The signed key is org-scoped so a tenant cannot read/write outside its prefix
 * - MinIO (local dev) and R2 (prod) share the same signing path
 * - Mocks @aws-sdk/client-s3 and @aws-sdk/s3-request-presigner — never hits real R2
 */

const getSignedUrl = vi.fn();
vi.mock("@aws-sdk/s3-request-presigner", () => ({
  getSignedUrl: (...args: unknown[]) => getSignedUrl(...args),
}));

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

const r2Handle = {
  client: { __s3: true } as unknown as never,
  bucket: "papercrane-prod",
  endpoint: "https://acct.r2.cloudflarestorage.com",
};

const minioHandle = {
  client: { __s3: true } as unknown as never,
  bucket: "papercrane-local",
  endpoint: "http://localhost:9000",
};

describe("presignPut — content-type + max-size + expiry", () => {
  beforeEach(() => {
    getSignedUrl.mockReset();
    getSignedUrl.mockResolvedValue("https://signed.example/put");
  });

  it("binds content-type, content-length, and 15-min expiry into the signature", async () => {
    const { presignPut, DEFAULT_PRESIGN_TTL_SEC } = await import("../presign");
    expect(DEFAULT_PRESIGN_TTL_SEC).toBe(15 * 60);

    const maxSize = 5 * 1024 * 1024; // 5 MB cap
    await presignPut(
      r2Handle,
      "orgs/acme/targets/t1/input.pdb",
      "chemical/x-pdb",
      maxSize,
    );

    const [, command, opts] = getSignedUrl.mock.calls[0]!;
    expect(command.__type).toBe("PutObjectCommand");
    expect(command.input.Bucket).toBe("papercrane-prod");
    expect(command.input.ContentType).toBe("chemical/x-pdb");
    expect(command.input.ContentLength).toBe(maxSize);

    expect(opts.expiresIn).toBe(DEFAULT_PRESIGN_TTL_SEC);
    expect(opts.signableHeaders).toBeInstanceOf(Set);
    expect(opts.signableHeaders.has("content-type")).toBe(true);
    expect(opts.signableHeaders.has("content-length")).toBe(true);
  });

  it("omits content-length from signable headers when not provided", async () => {
    const { presignPut } = await import("../presign");
    await presignPut(r2Handle, "orgs/acme/up.bin", "application/octet-stream");
    const [, command, opts] = getSignedUrl.mock.calls[0]!;
    expect(command.input.ContentLength).toBeUndefined();
    expect(opts.signableHeaders.has("content-length")).toBe(false);
  });

  it("uses the same signing surface for MinIO (local) as for R2 (prod)", async () => {
    const { presignPut } = await import("../presign");
    await presignPut(minioHandle, "orgs/acme/up.bin", "text/plain", 1024, 60);
    const [client, command, opts] = getSignedUrl.mock.calls[0]!;
    expect(client).toBe(minioHandle.client);
    expect(command.input.Bucket).toBe("papercrane-local");
    expect(opts.expiresIn).toBe(60);
  });
});

describe("presign — org_id-scoped path prefix prevents cross-tenant access", () => {
  beforeEach(() => {
    getSignedUrl.mockReset();
    getSignedUrl.mockResolvedValue("https://signed.example/put");
  });

  it("only signs keys under the caller's orgs/{orgId}/ prefix (paths helper)", async () => {
    const { orgTargetKey, jobDesignKey } = await import("../paths");

    // Tenant A and tenant B build keys via the paths helper.
    const acmeKey = orgTargetKey("acme", "t1");
    const widgetsKey = jobDesignKey("widgets", "j7", 0);

    expect(acmeKey).toBe("orgs/acme/targets/t1/input.pdb");
    expect(widgetsKey).toBe("orgs/widgets/jobs/j7/designs/0.cif");
    expect(acmeKey.startsWith("orgs/acme/")).toBe(true);
    expect(widgetsKey.startsWith("orgs/widgets/")).toBe(true);
    // No overlap: acme cannot construct a key into widgets' prefix.
    expect(acmeKey.includes("widgets")).toBe(false);
  });

  it("rejects path-traversal attempts in org/job ids", async () => {
    const { orgTargetKey } = await import("../paths");
    expect(() => orgTargetKey("../widgets", "t1")).toThrow();
    expect(() => orgTargetKey("acme", "../../../etc/passwd")).toThrow();
    expect(() => orgTargetKey("acme/widgets", "t1")).toThrow();
  });

  it("signs keys exactly as supplied — never rewrites or re-prefixes them", async () => {
    const { presignPut } = await import("../presign");
    const { orgTargetKey } = await import("../paths");
    const key = orgTargetKey("acme", "t1");

    await presignPut(r2Handle, key, "chemical/x-pdb", 1024);

    const [, command] = getSignedUrl.mock.calls[0]!;
    // Key must round-trip verbatim — any silent mutation is a tenant-isolation bug.
    expect(command.input.Key).toBe("orgs/acme/targets/t1/input.pdb");
  });
});

describe("presign — TTL guard rails", () => {
  beforeEach(() => {
    getSignedUrl.mockReset();
    getSignedUrl.mockResolvedValue("https://signed.example/get");
  });

  it("rejects TTLs above the SigV4 7-day cap before invoking the signer", async () => {
    const { presignPut } = await import("../presign");
    await expect(
      presignPut(r2Handle, "k", "text/plain", undefined, 7 * 24 * 60 * 60 + 1),
    ).rejects.toThrow(/SigV4/);
    expect(getSignedUrl).not.toHaveBeenCalled();
  });

  it("rejects non-positive or non-integer TTLs", async () => {
    const { presignPut } = await import("../presign");
    await expect(
      presignPut(r2Handle, "k", "text/plain", undefined, 0),
    ).rejects.toThrow(/ttlSec/);
    await expect(
      presignPut(r2Handle, "k", "text/plain", undefined, 1.5),
    ).rejects.toThrow(/ttlSec/);
  });
});
