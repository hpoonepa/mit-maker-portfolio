import type { FastifyInstance } from "fastify";
import { promises as fs } from "node:fs";
import path from "node:path";

/**
 * Max upload size for the dev stub. Must be >= the real cap enforced by
 * `createFromUpload` (UPLOAD_MAX_BYTES = 10 MB in the trpc targets router) so
 * structure files up to that size reach the handler. Fastify's default
 * bodyLimit is only 1 MB, which 413s any mmCIF over ~1 MB (e.g. a 1.1 MB GPCR
 * like 6X1A) before it ever hits the route.
 */
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

export interface DevStubOptions {
  /**
   * Base directory for stored objects. Defaults to
   * `$TMPDIR|/tmp` + `papercrane-dev-stub`.
   */
  dir?: string;
}

/** Resolve the dev-stub storage directory (respects `TMPDIR`). */
export function resolveDevStubDir(dir?: string): string {
  return dir ?? path.join(process.env.TMPDIR || "/tmp", "papercrane-dev-stub");
}

/**
 * Dev-only object-storage stub. Emulates R2 presigned PUT/GET against local
 * disk so target uploads work without cloud creds. A browser PUTs the fetched
 * PDB/CIF here and a later GET (`commitUpload`) reads it back. Filesystem-backed
 * so bytes survive tsx-watch restarts. NEVER mounted in production — the caller
 * gates on `NODE_ENV`.
 *
 * The write path re-ensures its directory on EVERY request. A one-time startup
 * `mkdir` is fragile: `/tmp` is swept by the OS (reboot / periodic cleanup), and
 * once the dir vanished every upload threw `ENOENT` → 500 with no recovery.
 */
export async function registerDevStub(
  app: FastifyInstance,
  opts: DevStubOptions = {},
): Promise<void> {
  const DEV_STUB_DIR = resolveDevStubDir(opts.dir);
  await fs.mkdir(DEV_STUB_DIR, { recursive: true });

  const safeKeyPath = (rawKey: string): string => {
    // Replace path separators + control chars with `_` to keep keys flat under
    // DEV_STUB_DIR. Defensive hash-collapse against weird keys.
    const flat = rawKey.replace(/[\x00-\x1f]/g, "_").replace(/[/\\]/g, "_");
    return path.join(DEV_STUB_DIR, flat);
  };

  app.addContentTypeParser(
    ["application/octet-stream", "chemical/x-pdb", "chemical/x-cif", "text/plain"],
    { parseAs: "buffer" },
    (_req, body, done) => done(null, body),
  );

  app.put<{ Params: { "*": string } }>(
    "/dev-stub/put/*",
    { config: { public: true, rateLimit: false }, bodyLimit: MAX_UPLOAD_BYTES },
    async (req, reply) => {
      const key = decodeURIComponent(req.params["*"] ?? "");
      const body = req.body;
      if (!Buffer.isBuffer(body)) {
        return reply.code(400).send({ error: "expected binary body" });
      }
      const filePath = safeKeyPath(key);
      // Re-ensure the directory on every write — /tmp is volatile and a
      // startup-only mkdir leaves writes to ENOENT once the OS sweeps it.
      await fs.mkdir(path.dirname(filePath), { recursive: true });
      await fs.writeFile(filePath, new Uint8Array(body));
      req.log.info(
        { key, bytes: body.byteLength, path: filePath },
        "dev-stub: upload stored",
      );
      return reply.code(204).send();
    },
  );

  app.get<{ Params: { "*": string } }>(
    "/dev-stub/get/*",
    { config: { public: true, rateLimit: false } },
    async (req, reply) => {
      const key = decodeURIComponent(req.params["*"] ?? "");
      const filePath = safeKeyPath(key);
      try {
        const buf = await fs.readFile(filePath);
        return reply
          .code(200)
          .header("content-type", "application/octet-stream")
          .send(buf);
      } catch {
        return reply.code(404).send({ error: "key not found in dev stub" });
      }
    },
  );
}
