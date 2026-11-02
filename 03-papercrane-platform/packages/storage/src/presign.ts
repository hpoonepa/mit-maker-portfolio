import { GetObjectCommand, PutObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import type { R2Handle } from "./client";

/** Default TTL for presigned URLs — 15 minutes, per plan 01 §6. */
export const DEFAULT_PRESIGN_TTL_SEC = 15 * 60;

/** Upper bound we accept from callers. 7 days is the SigV4 hard cap. */
const MAX_TTL_SEC = 7 * 24 * 60 * 60;

function assertTtl(ttlSec: number): void {
  if (
    typeof ttlSec !== "number" ||
    !Number.isFinite(ttlSec) ||
    !Number.isInteger(ttlSec) ||
    ttlSec <= 0
  ) {
    throw new Error("storage/presign: ttlSec must be a positive integer");
  }
  if (ttlSec > MAX_TTL_SEC) {
    throw new Error(
      `storage/presign: ttlSec ${ttlSec} exceeds SigV4 max ${MAX_TTL_SEC}`,
    );
  }
}

function assertKey(key: unknown): asserts key is string {
  if (typeof key !== "string" || key.length === 0) {
    throw new Error("storage/presign: key must be a non-empty string");
  }
}

/**
 * Presigned GET URL for downloading an existing object.
 *
 * @param handle  R2 client handle from `createR2Client`
 * @param key     Object key within the handle's bucket
 * @param ttlSec  Lifetime in seconds (default 15 min)
 */
export async function presignGet(
  handle: R2Handle,
  key: string,
  ttlSec: number = DEFAULT_PRESIGN_TTL_SEC,
): Promise<string> {
  assertKey(key);
  assertTtl(ttlSec);
  const command = new GetObjectCommand({
    Bucket: handle.bucket,
    Key: key,
  });
  return getSignedUrl(handle.client, command, { expiresIn: ttlSec });
}

/**
 * Presigned PUT URL for uploading an object with server-side size and
 * content-type enforcement. Both `contentType` and `contentLength` are
 * bound into the signature so a client cannot alter them.
 *
 * @param handle         R2 client handle
 * @param key            Destination object key
 * @param contentType    MIME type expected at upload time
 * @param contentLength  Exact byte length expected (optional)
 * @param ttlSec         Lifetime in seconds (default 15 min)
 */
export async function presignPut(
  handle: R2Handle,
  key: string,
  contentType: string,
  contentLength?: number,
  ttlSec: number = DEFAULT_PRESIGN_TTL_SEC,
): Promise<string> {
  assertKey(key);
  if (typeof contentType !== "string" || contentType.length === 0) {
    throw new Error("storage/presign: contentType must be a non-empty string");
  }
  if (contentLength !== undefined) {
    if (
      typeof contentLength !== "number" ||
      !Number.isInteger(contentLength) ||
      contentLength < 0
    ) {
      throw new Error(
        "storage/presign: contentLength must be a non-negative integer if provided",
      );
    }
  }
  assertTtl(ttlSec);

  const command = new PutObjectCommand({
    Bucket: handle.bucket,
    Key: key,
    ContentType: contentType,
    ...(contentLength !== undefined ? { ContentLength: contentLength } : {}),
  });

  const signableHeaders = new Set<string>(["content-type"]);
  if (contentLength !== undefined) {
    signableHeaders.add("content-length");
  }

  return getSignedUrl(handle.client, command, {
    expiresIn: ttlSec,
    signableHeaders,
  });
}
