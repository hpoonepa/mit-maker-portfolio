import Fastify from "fastify";
import { promises as fs } from "node:fs";
import path from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import { registerDevStub } from "../../src/routes/rest/devStub.js";

/**
 * Regression test for the dev-stub storage endpoint.
 *
 * Bug: the storage directory was created once at server startup, but volatile
 * `/tmp` gets swept by the OS. Once the dir vanished, every PUT threw
 * `ENOENT: ... open '/tmp/papercrane-dev-stub/...'` → 500 on "Create target".
 *
 * The fix re-ensures the directory on every write. The key test deletes the
 * dir AFTER the app is built, then PUTs — proving the write path self-heals
 * rather than relying on the startup mkdir.
 */

const TEST_DIR = path.join(
  process.env.TMPDIR || "/tmp",
  `papercrane-dev-stub-test-${process.pid}`,
);

async function buildApp() {
  const app = Fastify({ logger: false });
  await registerDevStub(app, { dir: TEST_DIR });
  return app;
}

afterAll(async () => {
  await fs.rm(TEST_DIR, { recursive: true, force: true });
});

describe("dev-stub storage", () => {
  it("stores a PUT body and 204s even when the dir was removed after startup", async () => {
    const app = await buildApp();
    // Simulate /tmp being swept AFTER the startup mkdir ran.
    await fs.rm(TEST_DIR, { recursive: true, force: true });

    const res = await app.inject({
      method: "PUT",
      url: "/dev-stub/put/orgs%2Fabc%2Fuploads%2Fdef%2F5MV5.cif",
      headers: { "content-type": "chemical/x-cif" },
      payload: Buffer.from("data_5MV5\n_entry.id 5MV5\n"),
    });

    expect(res.statusCode).toBe(204);
    const stored = await fs.readFile(
      path.join(TEST_DIR, "orgs_abc_uploads_def_5MV5.cif"),
      "utf8",
    );
    expect(stored).toContain("5MV5");
    await app.close();
  });

  it("accepts a structure upload larger than Fastify's 1MB default (regression: 413 FST_ERR_CTP_BODY_TOO_LARGE)", async () => {
    const app = await buildApp();
    // ~1.2 MB — over Fastify's 1MB default, like a real mmCIF (6X1A is 1.1 MB).
    const big = Buffer.alloc(1_200_000, 0x41);
    const res = await app.inject({
      method: "PUT",
      url: "/dev-stub/put/orgs%2Fa%2Fuploads%2Fb%2Fbig.cif",
      headers: { "content-type": "chemical/x-cif" },
      payload: big,
    });
    expect(res.statusCode).toBe(204);
    await app.close();
  });

  it("round-trips PUT then GET", async () => {
    const app = await buildApp();
    await app.inject({
      method: "PUT",
      url: "/dev-stub/put/k%2Ffile.bin",
      headers: { "content-type": "application/octet-stream" },
      payload: Buffer.from("hello-bytes"),
    });
    const get = await app.inject({
      method: "GET",
      url: "/dev-stub/get/k%2Ffile.bin",
    });
    expect(get.statusCode).toBe(200);
    expect(get.body).toBe("hello-bytes");
    await app.close();
  });

  it("404s on a key that was never stored", async () => {
    const app = await buildApp();
    const get = await app.inject({
      method: "GET",
      url: "/dev-stub/get/missing%2Fnope.bin",
    });
    expect(get.statusCode).toBe(404);
    await app.close();
  });
});
