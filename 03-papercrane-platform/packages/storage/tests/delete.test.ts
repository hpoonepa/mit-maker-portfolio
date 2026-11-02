import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * deletePrefix contract:
 * - Pages ListObjectsV2 using ContinuationToken until IsTruncated=false
 * - Batches DeleteObjects in chunks (max 1,000 keys per call)
 * - Returns total deleted count and any per-key errors
 * - Refuses dangerous prefixes ("", "/", "*")
 */

// Mark each command construction so we can identify it by type in send().
vi.mock("@aws-sdk/client-s3", () => ({
  S3Client: vi.fn(),
  ListObjectsV2Command: vi.fn().mockImplementation((input: unknown) => ({
    __type: "ListObjectsV2Command",
    input,
  })),
  DeleteObjectsCommand: vi.fn().mockImplementation((input: unknown) => ({
    __type: "DeleteObjectsCommand",
    input,
  })),
  DeleteObjectCommand: vi.fn().mockImplementation((input: unknown) => ({
    __type: "DeleteObjectCommand",
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

describe("deleteObject", () => {
  it("issues a single DeleteObjectCommand", async () => {
    const handle = makeHandle();
    handle.client.send.mockResolvedValue({});
    const { deleteObject } = await import("../src/delete");
    await deleteObject(handle as never, "orgs/o/jobs/j/designs/0.cif");
    expect(handle.client.send).toHaveBeenCalledTimes(1);
    const cmd = handle.client.send.mock.calls[0]?.[0] as {
      __type: string;
      input: { Bucket: string; Key: string };
    };
    expect(cmd.__type).toBe("DeleteObjectCommand");
    expect(cmd.input).toEqual({
      Bucket: "papercrane-prod",
      Key: "orgs/o/jobs/j/designs/0.cif",
    });
  });

  it("rejects empty key", async () => {
    const handle = makeHandle();
    const { deleteObject } = await import("../src/delete");
    await expect(deleteObject(handle as never, "")).rejects.toThrow(/key/);
    expect(handle.client.send).not.toHaveBeenCalled();
  });
});

describe("deletePrefix", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists then batch-deletes in one page", async () => {
    const handle = makeHandle();
    handle.client.send.mockImplementation(async (cmd: { __type: string }) => {
      if (cmd.__type === "ListObjectsV2Command") {
        return {
          Contents: [{ Key: "a" }, { Key: "b" }, { Key: "c" }],
          IsTruncated: false,
        };
      }
      if (cmd.__type === "DeleteObjectsCommand") {
        return { Deleted: [{ Key: "a" }, { Key: "b" }, { Key: "c" }] };
      }
      throw new Error(`unexpected: ${cmd.__type}`);
    });

    const { deletePrefix } = await import("../src/delete");
    const result = await deletePrefix(handle as never, "orgs/o/jobs/j/");

    expect(result).toEqual({ deleted: 3, errors: [] });

    const types = handle.client.send.mock.calls.map(
      (c) => (c[0] as { __type: string }).__type,
    );
    expect(types).toEqual(["ListObjectsV2Command", "DeleteObjectsCommand"]);

    const listInput = handle.client.send.mock.calls[0]?.[0] as {
      input: { Bucket: string; Prefix: string; ContinuationToken?: string };
    };
    expect(listInput.input.Bucket).toBe("papercrane-prod");
    expect(listInput.input.Prefix).toBe("orgs/o/jobs/j/");
    expect(listInput.input.ContinuationToken).toBeUndefined();

    const deleteInput = handle.client.send.mock.calls[1]?.[0] as {
      input: { Delete: { Objects: Array<{ Key: string }>; Quiet: boolean } };
    };
    expect(deleteInput.input.Delete.Objects).toEqual([
      { Key: "a" },
      { Key: "b" },
      { Key: "c" },
    ]);
    expect(deleteInput.input.Delete.Quiet).toBe(true);
  });

  it("pages through continuation tokens", async () => {
    const handle = makeHandle();
    let listCall = 0;
    handle.client.send.mockImplementation(async (cmd: { __type: string }) => {
      if (cmd.__type === "ListObjectsV2Command") {
        listCall += 1;
        if (listCall === 1) {
          return {
            Contents: [{ Key: "p1-a" }, { Key: "p1-b" }],
            IsTruncated: true,
            NextContinuationToken: "tok-1",
          };
        }
        if (listCall === 2) {
          return {
            Contents: [{ Key: "p2-a" }],
            IsTruncated: true,
            NextContinuationToken: "tok-2",
          };
        }
        return { Contents: [{ Key: "p3-a" }], IsTruncated: false };
      }
      if (cmd.__type === "DeleteObjectsCommand") {
        return {};
      }
      throw new Error(`unexpected: ${cmd.__type}`);
    });

    const { deletePrefix } = await import("../src/delete");
    const result = await deletePrefix(handle as never, "orgs/o/jobs/j/");

    // 3 list pages + 3 delete batches = 6 sends
    expect(handle.client.send).toHaveBeenCalledTimes(6);
    expect(result.deleted).toBe(4);
    expect(result.errors).toEqual([]);

    // Continuation tokens must be threaded through subsequent list calls.
    const listCalls = handle.client.send.mock.calls.filter(
      (c) => (c[0] as { __type: string }).__type === "ListObjectsV2Command",
    );
    expect(
      (listCalls[0]?.[0] as { input: { ContinuationToken?: string } }).input
        .ContinuationToken,
    ).toBeUndefined();
    expect(
      (listCalls[1]?.[0] as { input: { ContinuationToken?: string } }).input
        .ContinuationToken,
    ).toBe("tok-1");
    expect(
      (listCalls[2]?.[0] as { input: { ContinuationToken?: string } }).input
        .ContinuationToken,
    ).toBe("tok-2");
  });

  it("handles an empty prefix (no keys) without issuing a DeleteObjects call", async () => {
    const handle = makeHandle();
    handle.client.send.mockImplementation(async (cmd: { __type: string }) => {
      if (cmd.__type === "ListObjectsV2Command") {
        return { Contents: [], IsTruncated: false };
      }
      throw new Error(`unexpected: ${cmd.__type}`);
    });

    const { deletePrefix } = await import("../src/delete");
    const result = await deletePrefix(handle as never, "orgs/o/jobs/j/");

    expect(result).toEqual({ deleted: 0, errors: [] });
    const deleteCalls = handle.client.send.mock.calls.filter(
      (c) => (c[0] as { __type: string }).__type === "DeleteObjectsCommand",
    );
    expect(deleteCalls).toHaveLength(0);
  });

  it("collects per-key errors and subtracts them from the deleted count", async () => {
    const handle = makeHandle();
    handle.client.send.mockImplementation(async (cmd: { __type: string }) => {
      if (cmd.__type === "ListObjectsV2Command") {
        return {
          Contents: [{ Key: "a" }, { Key: "b" }, { Key: "c" }],
          IsTruncated: false,
        };
      }
      if (cmd.__type === "DeleteObjectsCommand") {
        return {
          Errors: [{ Key: "b", Code: "AccessDenied", Message: "nope" }],
        };
      }
      throw new Error(`unexpected: ${cmd.__type}`);
    });

    const { deletePrefix } = await import("../src/delete");
    const result = await deletePrefix(handle as never, "orgs/o/jobs/j/");
    expect(result.deleted).toBe(2);
    expect(result.errors).toEqual([{ key: "b", message: "nope" }]);
  });

  it("batches more than 1,000 keys into multiple DeleteObjects calls", async () => {
    const handle = makeHandle();
    const many = Array.from({ length: 1500 }, (_, i) => ({ Key: `k${i}` }));
    handle.client.send.mockImplementation(async (cmd: { __type: string }) => {
      if (cmd.__type === "ListObjectsV2Command") {
        return { Contents: many, IsTruncated: false };
      }
      if (cmd.__type === "DeleteObjectsCommand") return {};
      throw new Error(`unexpected: ${cmd.__type}`);
    });

    const { deletePrefix } = await import("../src/delete");
    const result = await deletePrefix(handle as never, "orgs/o/jobs/j/");

    const deleteCalls = handle.client.send.mock.calls.filter(
      (c) => (c[0] as { __type: string }).__type === "DeleteObjectsCommand",
    );
    expect(deleteCalls).toHaveLength(2);
    const first = deleteCalls[0]?.[0] as {
      input: { Delete: { Objects: Array<{ Key: string }> } };
    };
    const second = deleteCalls[1]?.[0] as {
      input: { Delete: { Objects: Array<{ Key: string }> } };
    };
    expect(first.input.Delete.Objects).toHaveLength(1000);
    expect(second.input.Delete.Objects).toHaveLength(500);
    expect(result.deleted).toBe(1500);
  });

  it("rejects empty / dangerous prefixes before any list call", async () => {
    const handle = makeHandle();
    const { deletePrefix } = await import("../src/delete");
    await expect(deletePrefix(handle as never, "")).rejects.toThrow(/prefix/);
    await expect(deletePrefix(handle as never, "/")).rejects.toThrow(
      /dangerous/,
    );
    await expect(deletePrefix(handle as never, "*")).rejects.toThrow(
      /dangerous/,
    );
    expect(handle.client.send).not.toHaveBeenCalled();
  });
});
