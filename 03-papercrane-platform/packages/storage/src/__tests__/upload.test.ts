import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Upload tests for Wave 8:
 * - server-side checksums (sha256Tee/Stream) match the expected digest
 * - multipart upload assembles parts in order with correct part numbers + ETags
 * - on error the in-flight multipart upload is aborted (no orphan parts in R2)
 * - small bodies bypass multipart and go through a single PutObject
 *
 * Mocks @aws-sdk/client-s3 — no real R2/MinIO traffic.
 */

vi.mock("@aws-sdk/client-s3", () => ({
  S3Client: vi.fn(),
  PutObjectCommand: vi.fn().mockImplementation((input: unknown) => ({
    __type: "PutObjectCommand",
    input,
  })),
  CreateMultipartUploadCommand: vi.fn().mockImplementation((input: unknown) => ({
    __type: "CreateMultipartUploadCommand",
    input,
  })),
  UploadPartCommand: vi.fn().mockImplementation((input: unknown) => ({
    __type: "UploadPartCommand",
    input,
  })),
  CompleteMultipartUploadCommand: vi
    .fn()
    .mockImplementation((input: unknown) => ({
      __type: "CompleteMultipartUploadCommand",
      input,
    })),
  AbortMultipartUploadCommand: vi.fn().mockImplementation((input: unknown) => ({
    __type: "AbortMultipartUploadCommand",
    input,
  })),
}));

type FakeHandle = {
  client: { send: ReturnType<typeof vi.fn> };
  bucket: string;
  endpoint: string;
};

function makeHandle(): FakeHandle {
  return {
    client: { send: vi.fn() },
    bucket: "papercrane-prod",
    endpoint: "https://acct.r2.cloudflarestorage.com",
  };
}

async function* asyncFrom(chunks: Uint8Array[]): AsyncGenerator<Uint8Array> {
  for (const c of chunks) yield c;
}

describe("uploadObject — small body single PutObject", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("issues exactly one PutObjectCommand with body, content-type, and metadata", async () => {
    const handle = makeHandle();
    handle.client.send.mockResolvedValue({});
    const { uploadObject } = await import("../upload");

    const body = new Uint8Array([1, 2, 3, 4]);
    await uploadObject(handle as never, "orgs/acme/jobs/j1/tiny.bin", body, {
      contentType: "application/octet-stream",
      meta: { sha256: "deadbeef" },
    });

    expect(handle.client.send).toHaveBeenCalledTimes(1);
    const cmd = handle.client.send.mock.calls[0]?.[0] as {
      __type: string;
      input: {
        Bucket: string;
        Key: string;
        Body: Uint8Array;
        ContentType: string;
        Metadata: Record<string, string>;
      };
    };
    expect(cmd.__type).toBe("PutObjectCommand");
    expect(cmd.input.Body).toBe(body);
    expect(cmd.input.ContentType).toBe("application/octet-stream");
    expect(cmd.input.Metadata).toEqual({ sha256: "deadbeef" });
  });
});

describe("checksum — server-side sha256 matches expected digest", () => {
  it("sha256Stream produces the correct hex digest for known input", async () => {
    const { sha256Stream } = await import("../checksum");
    // sha256("hello") = 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824
    const digest = await sha256Stream(asyncFrom([new Uint8Array(Buffer.from("hello"))]));
    expect(digest).toBe(
      "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
    );
  });

  it("sha256Tee yields chunks unchanged AND resolves a digest equal to a one-shot hash", async () => {
    const { sha256Tee, sha256Stream } = await import("../checksum");
    const chunks = [
      new Uint8Array(Buffer.from("paper")),
      new Uint8Array(Buffer.from("crane")),
    ];

    const tee = sha256Tee(asyncFrom(chunks));
    const seen: Uint8Array[] = [];
    for await (const c of tee.stream) seen.push(c);
    const teeDigest = await tee.digest;

    // Pass-through fidelity: original bytes preserved in original order.
    expect(Buffer.concat(seen).toString()).toBe("papercrane");

    // Tee digest equals a fresh sha256Stream over the same bytes.
    const fresh = await sha256Stream(asyncFrom(chunks.map((c) => new Uint8Array(c))));
    expect(teeDigest).toBe(fresh);
  });
});

describe("multipartUpload — assembly + abort-on-error", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("re-packs chunks into uniform parts and completes with ETags in order", async () => {
    const handle = makeHandle();
    let nextEtag = 0;
    handle.client.send.mockImplementation(async (cmd: { __type: string }) => {
      if (cmd.__type === "CreateMultipartUploadCommand") {
        return { UploadId: "upload-xyz" };
      }
      if (cmd.__type === "UploadPartCommand") {
        nextEtag += 1;
        return { ETag: `"etag-${nextEtag}"` };
      }
      if (cmd.__type === "CompleteMultipartUploadCommand") {
        return {};
      }
      throw new Error(`unexpected: ${cmd.__type}`);
    });

    const { multipartUpload, MULTIPART_PART_SIZE_BYTES } = await import(
      "../upload"
    );

    // Three full parts worth of data (24 MB total when part size is 8 MB).
    const part = new Uint8Array(MULTIPART_PART_SIZE_BYTES);
    const tail = new Uint8Array(1024); // small trailer flushed as final part
    await multipartUpload(
      handle as never,
      "orgs/acme/jobs/j1/big.bin",
      asyncFrom([part, part, part, tail]),
      { contentType: "application/octet-stream" },
    );

    const types = handle.client.send.mock.calls.map(
      (c) => (c[0] as { __type: string }).__type,
    );

    // Order: Create, then N UploadPart, then Complete.
    expect(types[0]).toBe("CreateMultipartUploadCommand");
    expect(types[types.length - 1]).toBe("CompleteMultipartUploadCommand");
    const partTypes = types.slice(1, -1);
    expect(partTypes.every((t) => t === "UploadPartCommand")).toBe(true);
    expect(partTypes.length).toBe(4); // 3 full parts + 1 trailer

    // Complete call must reference the same UploadId and submit parts in numeric order.
    const completeCall = handle.client.send.mock.calls.find(
      (c) =>
        (c[0] as { __type: string }).__type === "CompleteMultipartUploadCommand",
    )?.[0] as {
      input: {
        UploadId: string;
        MultipartUpload: {
          Parts: Array<{ PartNumber: number; ETag: string }>;
        };
      };
    };
    expect(completeCall.input.UploadId).toBe("upload-xyz");
    const parts = completeCall.input.MultipartUpload.Parts;
    expect(parts.map((p) => p.PartNumber)).toEqual([1, 2, 3, 4]);
    expect(parts.map((p) => p.ETag)).toEqual([
      '"etag-1"',
      '"etag-2"',
      '"etag-3"',
      '"etag-4"',
    ]);
  });

  it("aborts the multipart upload if a part fails — no orphan parts left in R2", async () => {
    const handle = makeHandle();
    handle.client.send.mockImplementation(async (cmd: { __type: string }) => {
      if (cmd.__type === "CreateMultipartUploadCommand") {
        return { UploadId: "upload-fail" };
      }
      if (cmd.__type === "UploadPartCommand") {
        throw new Error("boom: part failed");
      }
      if (cmd.__type === "AbortMultipartUploadCommand") {
        return {};
      }
      throw new Error(`unexpected: ${cmd.__type}`);
    });

    const { multipartUpload, MULTIPART_PART_SIZE_BYTES } = await import(
      "../upload"
    );
    const part = new Uint8Array(MULTIPART_PART_SIZE_BYTES);

    await expect(
      multipartUpload(
        handle as never,
        "orgs/acme/jobs/j1/big.bin",
        asyncFrom([part]),
      ),
    ).rejects.toThrow(/boom/);

    const types = handle.client.send.mock.calls.map(
      (c) => (c[0] as { __type: string }).__type,
    );
    expect(types).toContain("AbortMultipartUploadCommand");
    expect(types).not.toContain("CompleteMultipartUploadCommand");

    const abortCall = handle.client.send.mock.calls.find(
      (c) =>
        (c[0] as { __type: string }).__type === "AbortMultipartUploadCommand",
    )?.[0] as { input: { UploadId: string; Key: string } };
    expect(abortCall.input.UploadId).toBe("upload-fail");
    expect(abortCall.input.Key).toBe("orgs/acme/jobs/j1/big.bin");
  });
});
