import {
  AbortMultipartUploadCommand,
  CompleteMultipartUploadCommand,
  CreateMultipartUploadCommand,
  PutObjectCommand,
  UploadPartCommand,
  type CompletedPart,
} from "@aws-sdk/client-s3";
import type { R2Handle } from "./client";

/**
 * Size above which we switch to multipart upload. 50 MB matches the free-tier
 * target-size cap in plan 01 §6 — smaller bodies go via a single PutObject.
 */
export const MULTIPART_THRESHOLD_BYTES = 50 * 1024 * 1024;

/** Per-part size for multipart uploads. 8 MB = ~12.8 GB max per R2 5-MB minimum. */
export const MULTIPART_PART_SIZE_BYTES = 8 * 1024 * 1024;

export type UploadBody = Uint8Array | Buffer | string;

export interface UploadOptions {
  /** Optional MIME type. */
  contentType?: string;
  /**
   * Arbitrary string metadata echoed back on GetObject. Keys are lower-cased
   * by S3/R2 and limited to ASCII; we pass them through verbatim.
   */
  meta?: Record<string, string>;
}

/**
 * Upload a small body (< MULTIPART_THRESHOLD_BYTES) in a single request.
 * For large or unknown-length streams, use `multipartUpload` instead.
 */
export async function uploadObject(
  handle: R2Handle,
  key: string,
  body: UploadBody,
  options: UploadOptions = {},
): Promise<void> {
  if (typeof key !== "string" || key.length === 0) {
    throw new Error("storage/upload: key must be a non-empty string");
  }

  await handle.client.send(
    new PutObjectCommand({
      Bucket: handle.bucket,
      Key: key,
      Body: body,
      ...(options.contentType ? { ContentType: options.contentType } : {}),
      ...(options.meta ? { Metadata: options.meta } : {}),
    }),
  );
}

/**
 * Multipart upload helper for bodies larger than MULTIPART_THRESHOLD_BYTES.
 *
 * Accepts any async iterable of chunks (e.g. a Node `Readable` with
 * `[Symbol.asyncIterator]`). Chunks are re-packed into uniform parts of
 * `MULTIPART_PART_SIZE_BYTES`. On any error the multipart upload is aborted
 * so R2 doesn't accumulate orphaned parts.
 */
export async function multipartUpload(
  handle: R2Handle,
  key: string,
  body: AsyncIterable<Uint8Array>,
  options: UploadOptions = {},
): Promise<void> {
  if (typeof key !== "string" || key.length === 0) {
    throw new Error("storage/upload: key must be a non-empty string");
  }

  const create = await handle.client.send(
    new CreateMultipartUploadCommand({
      Bucket: handle.bucket,
      Key: key,
      ...(options.contentType ? { ContentType: options.contentType } : {}),
      ...(options.meta ? { Metadata: options.meta } : {}),
    }),
  );

  const uploadId = create.UploadId;
  if (!uploadId) {
    throw new Error("storage/upload: CreateMultipartUpload returned no UploadId");
  }

  const parts: CompletedPart[] = [];
  let partNumber = 1;
  let buffered: Uint8Array[] = [];
  let bufferedBytes = 0;

  async function flushPart(final: boolean): Promise<void> {
    if (bufferedBytes === 0 && !final) return;
    if (bufferedBytes === 0 && final && partNumber > 1) return;
    const partBody = concatChunks(buffered, bufferedBytes);
    buffered = [];
    bufferedBytes = 0;
    const result = await handle.client.send(
      new UploadPartCommand({
        Bucket: handle.bucket,
        Key: key,
        PartNumber: partNumber,
        UploadId: uploadId,
        Body: partBody,
      }),
    );
    parts.push({ PartNumber: partNumber, ETag: result.ETag });
    partNumber += 1;
  }

  try {
    for await (const chunk of body) {
      buffered.push(chunk);
      bufferedBytes += chunk.byteLength;
      if (bufferedBytes >= MULTIPART_PART_SIZE_BYTES) {
        await flushPart(false);
      }
    }
    await flushPart(true);

    if (parts.length === 0) {
      // Empty body — multipart needs at least one part. Upload a zero-byte part.
      const empty = await handle.client.send(
        new UploadPartCommand({
          Bucket: handle.bucket,
          Key: key,
          PartNumber: 1,
          UploadId: uploadId,
          Body: new Uint8Array(0),
        }),
      );
      parts.push({ PartNumber: 1, ETag: empty.ETag });
    }

    await handle.client.send(
      new CompleteMultipartUploadCommand({
        Bucket: handle.bucket,
        Key: key,
        UploadId: uploadId,
        MultipartUpload: { Parts: parts },
      }),
    );
  } catch (err) {
    await handle.client
      .send(
        new AbortMultipartUploadCommand({
          Bucket: handle.bucket,
          Key: key,
          UploadId: uploadId,
        }),
      )
      .catch(() => {
        // Swallow abort errors — we'll rethrow the original below.
      });
    throw err;
  }
}

function concatChunks(chunks: Uint8Array[], totalBytes: number): Uint8Array {
  const out = new Uint8Array(totalBytes);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.byteLength;
  }
  return out;
}
