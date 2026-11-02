import { createHash, type Hash } from "node:crypto";

/**
 * Compute a SHA-256 digest by streaming chunks through a hash.
 *
 * Accepts any async iterable of binary chunks — e.g. a Node `Readable`,
 * a web `ReadableStream` via `Symbol.asyncIterator`, or a manual generator.
 * Returns a lowercase hex digest.
 */
export async function sha256Stream(
  source: AsyncIterable<Uint8Array | Buffer | string>,
): Promise<string> {
  const hash: Hash = createHash("sha256");
  for await (const chunk of source) {
    if (typeof chunk === "string") {
      hash.update(chunk, "utf8");
    } else {
      // Buffer/Uint8Array — cast through Uint8Array for Node 22 type compatibility
      hash.update(chunk as Uint8Array);
    }
  }
  return hash.digest("hex");
}

/**
 * Tee-hash helper: wraps an async iterable, yielding each chunk unchanged
 * while feeding it into a SHA-256 hasher. The caller gets back both the
 * pass-through iterable and a promise that resolves to the final digest
 * after the iterable is exhausted.
 *
 * Use this to checksum an upload body without buffering it in memory.
 */
export function sha256Tee<T extends Uint8Array | Buffer>(
  source: AsyncIterable<T>,
): { stream: AsyncIterable<T>; digest: Promise<string> } {
  const hash = createHash("sha256");
  let resolveDigest!: (value: string) => void;
  let rejectDigest!: (reason: unknown) => void;
  const digest = new Promise<string>((resolve, reject) => {
    resolveDigest = resolve;
    rejectDigest = reject;
  });

  async function* pump(): AsyncGenerator<T> {
    try {
      for await (const chunk of source) {
        hash.update(chunk as Uint8Array);
        yield chunk;
      }
      resolveDigest(hash.digest("hex"));
    } catch (err) {
      rejectDigest(err);
      throw err;
    }
  }

  return { stream: pump(), digest };
}
