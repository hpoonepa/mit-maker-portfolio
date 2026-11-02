import { GetObjectCommand } from "@aws-sdk/client-s3";
import type { R2Handle } from "./client";

/**
 * Result of a streamed download.
 */
export interface StreamObjectResult {
  /** Web-standard ReadableStream of the object body. */
  body: ReadableStream<Uint8Array>;
  contentType?: string;
  contentLength?: number;
  etag?: string;
  /** User metadata (x-amz-meta-*) echoed back. */
  metadata?: Record<string, string>;
}

/**
 * Stream an object from R2 as a web-standard `ReadableStream`.
 *
 * The AWS SDK v3 returns `Body` as either a web `ReadableStream`, a Node
 * `Readable`, or (rarely) a blob. We normalise all three cases so callers
 * don't have to branch.
 */
export async function streamObject(
  handle: R2Handle,
  key: string,
): Promise<StreamObjectResult> {
  if (typeof key !== "string" || key.length === 0) {
    throw new Error("storage/download: key must be a non-empty string");
  }

  const response = await handle.client.send(
    new GetObjectCommand({ Bucket: handle.bucket, Key: key }),
  );

  const body = response.Body;
  if (body === undefined || body === null) {
    throw new Error(`storage/download: GetObject for ${key} returned no body`);
  }

  const stream = toWebStream(body);

  return {
    body: stream,
    contentType: response.ContentType,
    contentLength: response.ContentLength,
    etag: response.ETag,
    metadata: response.Metadata,
  };
}

function toWebStream(body: unknown): ReadableStream<Uint8Array> {
  // Already a web ReadableStream.
  if (typeof (body as ReadableStream<Uint8Array>)?.getReader === "function") {
    return body as ReadableStream<Uint8Array>;
  }

  // Node Readable — has `Symbol.asyncIterator` and typically a `.pipe`.
  const asyncIterable = body as AsyncIterable<Uint8Array> | null;
  if (
    asyncIterable !== null &&
    typeof asyncIterable === "object" &&
    typeof (asyncIterable as { [Symbol.asyncIterator]?: unknown })[
      Symbol.asyncIterator
    ] === "function"
  ) {
    return new ReadableStream<Uint8Array>({
      async start(controller) {
        try {
          for await (const chunk of asyncIterable) {
            controller.enqueue(
              chunk instanceof Uint8Array ? chunk : new Uint8Array(chunk),
            );
          }
          controller.close();
        } catch (err) {
          controller.error(err);
        }
      },
    });
  }

  throw new Error(
    "storage/download: unsupported body type returned by S3 client",
  );
}
