import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Client factory contract:
 * - `createR2Client` returns `{ client, bucket, endpoint }`
 * - Missing config throws with a list of missing env vars
 * - Endpoint is derived from `R2_ACCOUNT_ID` (R2 convention)
 * - Region is pinned to "auto"
 * - Credentials are threaded into S3Client config
 */

// Mock the AWS S3 client so we don't need network / real keys.
vi.mock("@aws-sdk/client-s3", () => {
  return {
    S3Client: vi.fn().mockImplementation((cfg: unknown) => ({ __cfg: cfg })),
  };
});

const ENV_KEYS = [
  "R2_ACCOUNT_ID",
  "R2_ACCESS_KEY_ID",
  "R2_SECRET_ACCESS_KEY",
  "R2_BUCKET",
  "R2_ENDPOINT",
];

describe("@papercrane/storage createR2Client", () => {
  const savedEnv: Record<string, string | undefined> = {};

  beforeEach(() => {
    for (const k of ENV_KEYS) {
      savedEnv[k] = process.env[k];
      delete process.env[k];
    }
  });

  afterEach(() => {
    for (const k of ENV_KEYS) {
      if (savedEnv[k] === undefined) delete process.env[k];
      else process.env[k] = savedEnv[k];
    }
    vi.clearAllMocks();
  });

  it("derives the endpoint from R2_ACCOUNT_ID when env is set", async () => {
    process.env.R2_ACCOUNT_ID = "acct_xyz";
    process.env.R2_ACCESS_KEY_ID = "ak";
    process.env.R2_SECRET_ACCESS_KEY = "sk";
    process.env.R2_BUCKET = "papercrane-prod";

    const { createR2Client } = await import("../src/client");
    const handle = createR2Client();
    expect(handle.bucket).toBe("papercrane-prod");
    expect(handle.endpoint).toBe("https://acct_xyz.r2.cloudflarestorage.com");
  });

  it("passes region=auto and credentials to S3Client", async () => {
    process.env.R2_ACCOUNT_ID = "acct_xyz";
    process.env.R2_ACCESS_KEY_ID = "ak";
    process.env.R2_SECRET_ACCESS_KEY = "sk";
    process.env.R2_BUCKET = "b";

    const s3mod = await import("@aws-sdk/client-s3");
    const { createR2Client } = await import("../src/client");
    createR2Client();
    const mockCtor = s3mod.S3Client as unknown as ReturnType<typeof vi.fn>;
    expect(mockCtor).toHaveBeenCalledTimes(1);
    const cfg = mockCtor.mock.calls[0]?.[0] as {
      region: string;
      endpoint: string;
      credentials: { accessKeyId: string; secretAccessKey: string };
    };
    expect(cfg.region).toBe("auto");
    expect(cfg.endpoint).toBe("https://acct_xyz.r2.cloudflarestorage.com");
    expect(cfg.credentials).toEqual({
      accessKeyId: "ak",
      secretAccessKey: "sk",
    });
  });

  it("lets overrides beat env vars", async () => {
    process.env.R2_ACCOUNT_ID = "from_env";
    process.env.R2_ACCESS_KEY_ID = "ak";
    process.env.R2_SECRET_ACCESS_KEY = "sk";
    process.env.R2_BUCKET = "env_bucket";

    const { createR2Client } = await import("../src/client");
    const handle = createR2Client({
      accountId: "override_acct",
      bucket: "override_bucket",
    });
    expect(handle.bucket).toBe("override_bucket");
    expect(handle.endpoint).toBe(
      "https://override_acct.r2.cloudflarestorage.com",
    );
  });

  it("throws listing every missing required field", async () => {
    const { createR2Client } = await import("../src/client");
    expect(() => createR2Client()).toThrow(
      /R2_ACCOUNT_ID.*R2_ACCESS_KEY_ID.*R2_SECRET_ACCESS_KEY.*R2_BUCKET/s,
    );
  });

  it("accepts explicit endpoint override (useful for local mock)", async () => {
    const { createR2Client } = await import("../src/client");
    const handle = createR2Client({
      accountId: "a",
      accessKeyId: "ak",
      secretAccessKey: "sk",
      bucket: "b",
      endpoint: "http://localhost:9000",
    });
    expect(handle.endpoint).toBe("http://localhost:9000");
  });

  it("r2Endpoint helper builds the expected URL shape", async () => {
    const { r2Endpoint } = await import("../src/client");
    expect(r2Endpoint("abc123")).toBe("https://abc123.r2.cloudflarestorage.com");
  });
});
