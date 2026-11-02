import {
  DeleteObjectCommand,
  DeleteObjectsCommand,
  ListObjectsV2Command,
  type ListObjectsV2CommandOutput,
  type ObjectIdentifier,
  type _Object,
} from "@aws-sdk/client-s3";
import type { R2Handle } from "./client";

/** S3/R2 DeleteObjects caps at 1,000 keys per call. */
const DELETE_BATCH_SIZE = 1000;

/** Page size we ask ListObjectsV2 for. 1,000 is the service max. */
const LIST_PAGE_SIZE = 1000;

/**
 * Delete a single object. No-ops if the key does not exist (R2 returns 204).
 */
export async function deleteObject(
  handle: R2Handle,
  key: string,
): Promise<void> {
  if (typeof key !== "string" || key.length === 0) {
    throw new Error("storage/delete: key must be a non-empty string");
  }
  await handle.client.send(
    new DeleteObjectCommand({ Bucket: handle.bucket, Key: key }),
  );
}

export interface DeletePrefixResult {
  deleted: number;
  errors: Array<{ key: string; message: string }>;
}

/**
 * Delete every object under a prefix.
 *
 * Implementation: loop ListObjectsV2 with the continuation token, batching
 * up to 1,000 keys per DeleteObjects call. This is what the retention
 * sweeper (plan 01 §6) uses to GC a job's artifacts after its TTL lapses.
 *
 * SAFETY: the prefix must be non-empty and must not be a top-level wildcard.
 * We refuse `""`, `"/"`, or anything that would match the entire bucket.
 */
export async function deletePrefix(
  handle: R2Handle,
  prefix: string,
): Promise<DeletePrefixResult> {
  if (typeof prefix !== "string" || prefix.length === 0) {
    throw new Error("storage/delete: prefix must be a non-empty string");
  }
  if (prefix === "/" || prefix === "*") {
    throw new Error(`storage/delete: refusing dangerous prefix "${prefix}"`);
  }

  let continuationToken: string | undefined = undefined;
  let deleted = 0;
  const errors: DeletePrefixResult["errors"] = [];

  do {
    const listResponse: ListObjectsV2CommandOutput = await handle.client.send(
      new ListObjectsV2Command({
        Bucket: handle.bucket,
        Prefix: prefix,
        MaxKeys: LIST_PAGE_SIZE,
        ...(continuationToken ? { ContinuationToken: continuationToken } : {}),
      }),
    );

    const contents: _Object[] = listResponse.Contents ?? [];
    const keys: ObjectIdentifier[] = contents
      .filter(
        (o: _Object): o is _Object & { Key: string } =>
          typeof o.Key === "string" && o.Key.length > 0,
      )
      .map((o: _Object & { Key: string }) => ({ Key: o.Key }));

    for (let i = 0; i < keys.length; i += DELETE_BATCH_SIZE) {
      const batch = keys.slice(i, i + DELETE_BATCH_SIZE);
      const del = await handle.client.send(
        new DeleteObjectsCommand({
          Bucket: handle.bucket,
          Delete: { Objects: batch, Quiet: true },
        }),
      );

      deleted += batch.length - (del.Errors?.length ?? 0);
      if (del.Errors) {
        for (const e of del.Errors) {
          errors.push({
            key: e.Key ?? "<unknown>",
            message: e.Message ?? e.Code ?? "unknown error",
          });
        }
      }
    }

    continuationToken = listResponse.IsTruncated
      ? listResponse.NextContinuationToken
      : undefined;
  } while (continuationToken);

  return { deleted, errors };
}
