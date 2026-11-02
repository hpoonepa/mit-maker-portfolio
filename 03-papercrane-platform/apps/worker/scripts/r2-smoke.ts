/**
 * Live R2 readiness check. Writes one uniquely-named object, reads it back,
 * verifies the bytes, then deletes it. No existing object is touched.
 */
import { randomUUID } from "node:crypto";
import {
  createR2Client,
  deleteObject,
  streamObject,
  uploadObject,
} from "@papercrane/storage";

async function main(): Promise<void> {
  const handle = createR2Client();
  const key = `readiness/storage-smoke/${randomUUID()}.txt`;
  const expected = `papercrane-r2-smoke:${randomUUID()}`;
  let uploaded = false;

  try {
    await uploadObject(handle, key, expected, {
      contentType: "text/plain; charset=utf-8",
      meta: { purpose: "readiness-smoke" },
    });
    uploaded = true;
    const stored = await streamObject(handle, key);
    const actual = await new Response(stored.body).text();
    if (actual !== expected) {
      throw new Error("R2 read-after-write returned different bytes");
    }
    process.stdout.write("R2 smoke passed: write, read, and byte verification succeeded.\n");
  } finally {
    if (uploaded) {
      await deleteObject(handle, key);
      process.stdout.write("R2 smoke cleanup passed.\n");
    }
  }
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`R2 smoke failed: ${message}\n`);
  process.exit(1);
});
