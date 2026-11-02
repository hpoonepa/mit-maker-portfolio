import { afterEach, describe, expect, it, vi } from "vitest";
import { uploadStructureFile } from "./upload";

class FailingDirectUpload {
  upload: {
    onprogress: ((event: ProgressEvent) => void) | null;
  } = { onprogress: null };
  status = 0;
  responseText = "";
  statusText = "";
  onload: ((event: ProgressEvent) => void) | null = null;
  onerror: ((event: ProgressEvent) => void) | null = null;
  ontimeout: ((event: ProgressEvent) => void) | null = null;
  onabort: ((event: ProgressEvent) => void) | null = null;

  open(): void {}
  setRequestHeader(): void {}
  abort(): void {
    this.onabort?.(new ProgressEvent("abort"));
  }
  send(): void {
    this.onerror?.(new ProgressEvent("error"));
  }
}

class RejectedDirectUpload extends FailingDirectUpload {
  override status = 403;
  override responseText = "forbidden";
  override statusText = "Forbidden";

  override send(): void {
    this.onload?.(new ProgressEvent("load"));
  }
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("uploadStructureFile", () => {
  it("falls back through the authenticated app route when browser-to-R2 is blocked", async () => {
    vi.stubGlobal("XMLHttpRequest", FailingDirectUpload);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["ATOM"], "5G51.cif", {
      type: "chemical/x-cif",
    });
    const progress: number[] = [];

    const result = await uploadStructureFile({
      file,
      getSignedUrl: async () => ({
        url: "https://papercrane.example/signed-put",
        uploadKey: "orgs/test/uploads/5G51.cif",
      }),
      onProgress: (value) => progress.push(value),
    });

    expect(result).toEqual({
      uploadKey: "orgs/test/uploads/5G51.cif",
      contentLength: 4,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/uploads/presigned");
    const request = fetchMock.mock.calls[0]?.[1];
    expect(request?.method).toBe("POST");
    const body = request?.body as FormData;
    expect(body.get("uploadUrl")).toBe(
      "https://papercrane.example/signed-put",
    );
    expect(body.get("file")).toBeInstanceOf(File);
    expect(progress).toEqual([10, 100]);
  });

  it("does not hide a real storage rejection behind the fallback", async () => {
    vi.stubGlobal("XMLHttpRequest", RejectedDirectUpload);
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["ATOM"], "target.pdb");

    await expect(
      uploadStructureFile({
        file,
        getSignedUrl: async () => ({
          url: "https://papercrane.example/signed-put",
          uploadKey: "orgs/test/uploads/target.pdb",
        }),
      }),
    ).rejects.toThrow("upload failed (403): forbidden");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
