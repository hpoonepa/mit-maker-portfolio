/**
 * Browser-side helper for streaming a structure file to R2 via a presigned
 * PUT URL. Handles progress reporting via XHR (fetch lacks request progress
 * in browsers as of writing).
 *
 * Usage:
 *
 *   await putToR2({
 *     url,
 *     file,
 *     contentType: "chemical/x-pdb",
 *     onProgress: (pct) => setProgress(pct),
 *   });
 */

export type UploadProgressFn = (pct: number) => void;

/**
 * The browser could not reach the presigned storage URL at all. The most
 * common cause is a bucket CORS policy that does not include the current
 * origin. This is deliberately distinct from an R2 HTTP rejection so the
 * high-level helper can retry through our authenticated same-origin proxy.
 */
export class DirectUploadUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DirectUploadUnavailableError";
  }
}

export interface PutToR2Options {
  /** Presigned PUT URL minted by `targets.getUploadUrl`. */
  url: string;
  /** The file (or raw bytes) to upload. */
  file: Blob;
  /** Must match the content-type bound into the presigned URL. */
  contentType?: string;
  /** Called with 0..100 as the upload streams. */
  onProgress?: UploadProgressFn;
  /** Abort signal: aborts the underlying XHR. */
  signal?: AbortSignal;
}

/**
 * PUTs `file` to `url`. Resolves on a 2xx response, rejects with the response
 * body for non-2xx (so callers can surface useful error messages).
 *
 * We use XMLHttpRequest because `fetch()` does not expose request upload
 * progress in browsers: the dropzone's "uploading 73%" indicator depends
 * on `xhr.upload.onprogress`.
 */
export function putToR2(opts: PutToR2Options): Promise<void> {
  const { url, file, contentType = "chemical/x-pdb", onProgress, signal } = opts;

  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("aborted", "AbortError"));
      return;
    }

    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url, true);
    xhr.setRequestHeader("Content-Type", contentType);

    xhr.upload.onprogress = (e) => {
      if (!onProgress || !e.lengthComputable || e.total === 0) return;
      onProgress(Math.min(100, Math.round((e.loaded / e.total) * 100)));
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(100);
        resolve();
      } else {
        reject(
          new Error(
            `upload failed (${xhr.status}): ${xhr.responseText.slice(0, 200) || xhr.statusText}`,
          ),
        );
      }
    };

    xhr.onerror = () =>
      reject(
        new DirectUploadUnavailableError(
          "direct workspace upload was blocked by the browser",
        ),
      );
    xhr.ontimeout = () =>
      reject(
        new DirectUploadUnavailableError("direct workspace upload timed out"),
      );
    xhr.onabort = () => reject(new DOMException("aborted", "AbortError"));

    if (signal) {
      const onAbort = () => {
        xhr.abort();
      };
      if (signal.aborted) {
        onAbort();
        return;
      }
      signal.addEventListener("abort", onAbort, { once: true });
    }

    xhr.send(file);
  });
}

export interface UploadFileToR2Result {
  uploadKey: string;
  contentLength: number;
}

/**
 * Upload through a same-origin route when the browser cannot call R2
 * directly. The route authenticates the session and only forwards URLs for
 * this PaperCrane R2 account, so it cannot be used as an open HTTP proxy.
 */
async function putThroughAppProxy(args: {
  url: string;
  file: File;
  contentType: string;
  signal?: AbortSignal;
}): Promise<void> {
  const body = new FormData();
  body.set("uploadUrl", args.url);
  body.set("file", args.file, args.file.name);
  body.set("contentType", args.contentType);

  const response = await fetch("/api/uploads/presigned", {
    method: "POST",
    body,
    signal: args.signal,
  });

  if (!response.ok) {
    const message = await response.text().catch(() => "");
    throw new Error(
      `workspace upload failed (${response.status}): ${
        message.slice(0, 200) || response.statusText
      }`,
    );
  }
}

/**
 * High-level helper used by the wizard:
 *   1. Asks the server for a presigned URL via the provided callback.
 *   2. Streams the file to R2 with progress.
 *   3. Returns the staging key the caller can pass to `createFromUpload`.
 *
 * The fetch of the URL is parameterised so the same function works in tests
 * (pass a stub) and in the live app (pass the trpc mutation's `mutateAsync`).
 */
export async function uploadStructureFile(args: {
  file: File;
  getSignedUrl: (input: {
    filename: string;
    contentLength: number;
  }) => Promise<{ url: string; uploadKey: string }>;
  onProgress?: UploadProgressFn;
  signal?: AbortSignal;
}): Promise<UploadFileToR2Result> {
  const { file, getSignedUrl, onProgress, signal } = args;
  const { url, uploadKey } = await getSignedUrl({
    filename: file.name,
    contentLength: file.size,
  });

  const contentType = "chemical/x-pdb";
  try {
    await putToR2({
      url,
      file,
      contentType,
      onProgress,
      signal,
    });
  } catch (error) {
    if (!(error instanceof DirectUploadUnavailableError)) throw error;

    // CORS and privacy extensions can block a browser-to-R2 request even
    // though the signed URL is valid. Keep the progress state active while
    // retrying through the authenticated app origin.
    onProgress?.(10);
    await putThroughAppProxy({ url, file, contentType, signal });
    onProgress?.(100);
  }

  return { uploadKey, contentLength: file.size };
}
