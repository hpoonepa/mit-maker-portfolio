/**
 * ModalProvider tests — happy path, cancellation, infra error, missing-token
 * fallback. Uses a mocked fetch to stand in for Modal's HTTP API.
 */

import { describe, it, expect, vi, beforeAll, afterAll } from "vitest";
import {
  assertOwnedArtifactKey,
  ensureOwnedModalArtifact,
  ModalProvider,
  resolveModalParams,
} from "../../src/providers/modal";
import { ModalClient } from "../../src/providers/modalClient";
import type { ToolManifest } from "@papercrane/tools-sdk";
import type { ProviderSpawnInputs } from "../../src/providers/types";

// Pin the workspace these tests assert against — `resolveModalFunction()`
// reads MODAL_WORKSPACE at call time and falls back to the dev default
// (`boozercam660`) otherwise.
beforeAll(() => {
  vi.stubEnv("MODAL_WORKSPACE", "papercrane-prod");
});
afterAll(() => {
  vi.unstubAllEnvs();
});

// ---------- fixtures ----------

function mkLogger() {
  const fn = () => vi.fn() as unknown as (...args: unknown[]) => void;
  const logger = {
    info: fn(),
    warn: fn(),
    error: fn(),
    debug: fn(),
    trace: fn(),
    fatal: fn(),
    child: () => logger,
  };
  return logger as unknown as import("@papercrane/observability").Logger & {
    info: ReturnType<typeof vi.fn>;
    warn: ReturnType<typeof vi.fn>;
  };
}

function mkManifest(overrides: Partial<ToolManifest> = {}): ToolManifest {
  return {
    id: "bindcraft",
    displayName: "BindCraft",
    version: "1.0.0",
    adapterVersion: "1",
    category: "binder_design",
    tier: "open",
    license: "MIT",
    image: "papercrane/bindcraft",
    imageDigest: "sha256:0",
    compute: {
      gpu: "A100",
      gpuCount: 1,
      cpuCores: 8,
      memoryGb: 32,
      estSecondsPerDesign: 10,
    },
    ...overrides,
  };
}

function mkInputs(
  overrides: Partial<ProviderSpawnInputs> = {},
): ProviderSpawnInputs {
  return {
    jobId: "job-1",
    orgId: "org-1",
    toolId: "bindcraft",
    tier: "pro",
    numSeeds: 3,
    request: { targetPdb: "r2://t.pdb" },
    ...overrides,
  };
}

function ndjsonStream(lines: string[]): Response {
  const body = lines.join("\n") + "\n";
  return new Response(body, {
    status: 200,
    headers: { "content-type": "application/x-ndjson" },
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/**
 * Build a fetch mock that routes by URL path. Returns the raw mock so tests
 * can inspect call counts.
 */
function mkFetchRouter(
  routes: Record<string, (init?: RequestInit) => Promise<Response> | Response>,
) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    for (const [pattern, handler] of Object.entries(routes)) {
      if (url.includes(pattern)) return handler(init);
    }
    return new Response(`no route for ${url}`, { status: 404 });
  });
}

describe("ModalProvider — parameter resolution", () => {
  it("merges manifest defaults while preserving explicit request precedence", () => {
    expect(
      resolveModalParams(
        { temperature: 0.1, numSamples: 5, mode: "default" },
        {
          params: { mode: "legacy", numSamples: 6 },
          toolParams: { temperature: 0.4, numSamples: 7 },
          numSamples: 8,
          targetPdb: "1ABC",
        },
      ),
    ).toMatchObject({
      temperature: 0.4,
      numSamples: 8,
      mode: "legacy",
      targetPdb: "1ABC",
    });
  });

  it("returns a fresh defaults object for an absent request", () => {
    const defaults = { temperature: 0.2 };
    expect(resolveModalParams(defaults, null)).toEqual(defaults);
    expect(resolveModalParams(defaults, null)).not.toBe(defaults);
  });
});

describe("ModalProvider — artifact ownership", () => {
  const params = {
    _papercrane: {
      artifactUploads: {
        "7": {
          url: "https://storage.test/upload-7",
          key: "orgs/org-1/jobs/job-1/designs/7.cif",
          contentType: "chemical/x-cif",
        },
      },
    },
  };

  it("accepts the exact worker-reserved artifact key", async () => {
    const fetchMock = vi.fn();
    await expect(
      ensureOwnedModalArtifact(
        {
          type: "seed",
          seed: 7,
          structureKey: "orgs/org-1/jobs/job-1/designs/7.cif",
        },
        params,
        fetchMock as unknown as typeof fetch,
      ),
    ).resolves.toBe("orgs/org-1/jobs/job-1/designs/7.cif");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("materializes sequence-only output at the reserved key", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 200 }));
    await expect(
      ensureOwnedModalArtifact(
        {
          type: "seed",
          seed: 7,
          sequence: "ACDE",
          artifactKey: "modal/job-1/7/scores.json",
        },
        params,
        fetchMock as unknown as typeof fetch,
      ),
    ).resolves.toBe("orgs/org-1/jobs/job-1/designs/7.cif");
    expect(fetchMock).toHaveBeenCalledWith(
      "https://storage.test/upload-7",
      expect.objectContaining({
        method: "PUT",
        body: expect.stringContaining("ACDE"),
      }),
    );
  });

  it("rejects an unowned structure path instead of persisting a broken key", async () => {
    await expect(
      ensureOwnedModalArtifact(
        {
          type: "seed",
          seed: 7,
          artifactKey: "modal/job-1/7/output.pdb",
        },
        params,
      ),
    ).rejects.toMatchObject({ code: "INVALID_OUTPUT", retryable: false });
  });

  it("classifies a sequence artifact network failure as retryable", async () => {
    const fetchMock = vi.fn(async () => {
      throw new TypeError("network down");
    });
    await expect(
      ensureOwnedModalArtifact(
        { type: "seed", seed: 7, sequence: "ACDE" },
        params,
        fetchMock as unknown as typeof fetch,
      ),
    ).rejects.toMatchObject({ code: "INFRA_ERROR", retryable: true });
  });

  it("rejects cross-organization and traversal input artifact keys", () => {
    expect(
      assertOwnedArtifactKey(
        "orgs/org-1/uploads/backbone.cif",
        "org-1",
        "target",
      ),
    ).toBe("orgs/org-1/uploads/backbone.cif");
    expect(() =>
      assertOwnedArtifactKey(
        "orgs/other/uploads/backbone.cif",
        "org-1",
        "target",
      ),
    ).toThrow(/outside this organization/);
    expect(() =>
      assertOwnedArtifactKey(
        "orgs/org-1/uploads/../secret.cif",
        "org-1",
        "target",
      ),
    ).toThrow(/outside this organization/);
    expect(() =>
      assertOwnedArtifactKey("orgs/org-1/", "org-1", "partner"),
    ).toThrow(/outside this organization/);
  });
});

// ---------- tests ----------

describe("ModalProvider — missing tokens (fallback)", () => {
  it("warns once on construction and emits fake seeds", async () => {
    const logger = mkLogger();
    const provider = new ModalProvider({ logger, seedIntervalMs: 1 });
    expect(logger.warn).toHaveBeenCalled();

    const result = await provider.spawnJob(
      mkManifest(),
      mkInputs({ numSeeds: 2 }),
    );
    const seeds: number[] = [];
    for await (const s of result.seeds) seeds.push(s.seed);
    expect(seeds).toEqual([1, 2]);
    expect(result.spawnId).toContain("modal-stub-");
  });
});

describe("ModalProvider — production fail-closed (no creds)", () => {
  it("throws instead of fabricating metrics when client is null AND NODE_ENV=production", async () => {
    const prev = process.env.NODE_ENV;
    process.env.NODE_ENV = "production";
    try {
      const logger = mkLogger();
      const provider = new ModalProvider({ logger, seedIntervalMs: 1 });
      await expect(
        provider.spawnJob(mkManifest(), mkInputs({ numSeeds: 2 })),
      ).rejects.toThrow(/refusing to run/i);
    } finally {
      if (prev === undefined) delete process.env.NODE_ENV;
      else process.env.NODE_ENV = prev;
    }
  });

  it("still returns the stub stream when client is null and NODE_ENV is not production", async () => {
    const prev = process.env.NODE_ENV;
    process.env.NODE_ENV = "development";
    try {
      const logger = mkLogger();
      const provider = new ModalProvider({ logger, seedIntervalMs: 1 });
      const result = await provider.spawnJob(
        mkManifest(),
        mkInputs({ numSeeds: 2 }),
      );
      const seeds: number[] = [];
      for await (const s of result.seeds) seeds.push(s.seed);
      expect(seeds).toEqual([1, 2]);
      expect(result.spawnId).toContain("modal-stub-");
    } finally {
      if (prev === undefined) delete process.env.NODE_ENV;
      else process.env.NODE_ENV = prev;
    }
  });

  it('stub metrics carry provenance: "stub" so fabricated rows self-identify', async () => {
    const prev = process.env.NODE_ENV;
    process.env.NODE_ENV = "development";
    try {
      const logger = mkLogger();
      const provider = new ModalProvider({ logger, seedIntervalMs: 1 });
      const result = await provider.spawnJob(
        mkManifest(),
        mkInputs({ numSeeds: 1 }),
      );
      const metricsSeen: Array<Record<string, unknown>> = [];
      for await (const s of result.seeds) metricsSeen.push(s.metrics);
      expect(metricsSeen[0]?.provenance).toBe("stub");
    } finally {
      if (prev === undefined) delete process.env.NODE_ENV;
      else process.env.NODE_ENV = prev;
    }
  });
});

describe("ModalProvider — storage fail-closed", () => {
  it("classifies missing R2 as a non-retryable configuration error", async () => {
    const provider = new ModalProvider({
      logger: mkLogger(),
      tokenId: "id",
      tokenSecret: "secret",
      workspace: "papercrane-prod",
    });

    await expect(
      provider.spawnJob(mkManifest(), mkInputs({ numSeeds: 1 })),
    ).rejects.toMatchObject({
      code: "RUNTIME_ERROR",
      message: expect.stringMatching(/R2 credentials are required/),
    });
  });
});

describe("ModalProvider — happy path", () => {
  it("applies manifest defaults on the injected-client compatibility path", async () => {
    let spawnBody: Record<string, unknown> | undefined;
    const fetchMock = mkFetchRouter({
      "/spawn": async (init) => {
        spawnBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
        return jsonResponse({ call_id: "call-default-params" });
      },
      "/stream": async () => ndjsonStream([JSON.stringify({ type: "done" })]),
    });
    const client = new ModalClient({
      tokenId: "id",
      tokenSecret: "secret",
      baseUrl: "https://api.modal.test",
      backoffMs: 1,
      fetchImpl: fetchMock as unknown as typeof fetch,
    });
    const provider = new ModalProvider({
      logger: mkLogger(),
      tokenId: "id",
      tokenSecret: "secret",
      client,
    });

    const result = await provider.spawnJob(
      mkManifest({ defaultParams: { temperature: 0.2, mode: "fast" } }),
      mkInputs({
        numSeeds: 1,
        request: { toolParams: { temperature: 0.6 }, targetPdb: "1ABC" },
      }),
    );
    for await (const _seed of result.seeds) {
      // no-op
    }

    expect(
      (spawnBody?.input as { request?: Record<string, unknown> })?.request,
    ).toMatchObject({ temperature: 0.6, mode: "fast", targetPdb: "1ABC" });
  });

  it("spawns call, streams seed events, completes on done", async () => {
    const logger = mkLogger();
    const fetchMock = mkFetchRouter({
      "/spawn": async () => jsonResponse({ call_id: "call-happy" }),
      "/stream": async () =>
        ndjsonStream([
          JSON.stringify({ type: "log", message: "starting" }),
          JSON.stringify({
            type: "seed",
            seed: 1,
            designId: "d-1",
            metrics: { ipsae: 0.8 },
            artifactKey: "orgs/org-1/jobs/job-1/designs/1.cif",
          }),
          JSON.stringify({
            type: "seed",
            seed: 2,
            designId: "d-2",
            metrics: { ipsae: 0.7 },
            artifactKey: "orgs/org-1/jobs/job-1/designs/2.cif",
          }),
          JSON.stringify({
            type: "seed",
            seed: 3,
            designId: "d-3",
            metrics: { ipsae: 0.6 },
            artifactKey: "orgs/org-1/jobs/job-1/designs/3.cif",
          }),
          JSON.stringify({ type: "done" }),
        ]),
    });

    const client = new ModalClient({
      tokenId: "id",
      tokenSecret: "secret",
      baseUrl: "https://api.modal.test",
      backoffMs: 1,
      fetchImpl: fetchMock as unknown as typeof fetch,
    });
    const provider = new ModalProvider({
      logger,
      tokenId: "id",
      tokenSecret: "secret",
      client,
    });

    const result = await provider.spawnJob(mkManifest(), mkInputs());
    expect(result.spawnId).toBe("call-happy");

    const collected: Array<{ seed: number; ipsae: number }> = [];
    for await (const s of result.seeds) {
      collected.push({ seed: s.seed, ipsae: s.metrics.ipsae as number });
    }
    expect(collected).toEqual([
      { seed: 1, ipsae: 0.8 },
      { seed: 2, ipsae: 0.7 },
      { seed: 3, ipsae: 0.6 },
    ]);
  });

  it("fills in missing designId/artifactKey with defaults", async () => {
    const logger = mkLogger();
    const fetchMock = mkFetchRouter({
      "/spawn": async () => jsonResponse({ call_id: "call-defaults" }),
      "/stream": async () =>
        ndjsonStream([
          JSON.stringify({ type: "seed", seed: 5, metrics: {} }),
          JSON.stringify({ type: "done" }),
        ]),
    });
    const client = new ModalClient({
      tokenId: "id",
      tokenSecret: "secret",
      baseUrl: "https://api.modal.test",
      backoffMs: 1,
      fetchImpl: fetchMock as unknown as typeof fetch,
    });
    const provider = new ModalProvider({
      logger,
      tokenId: "id",
      tokenSecret: "secret",
      client,
    });
    const result = await provider.spawnJob(
      mkManifest(),
      mkInputs({ numSeeds: 1 }),
    );
    const got: Array<{ designId: string; artifactKey: string }> = [];
    for await (const s of result.seeds)
      got.push({ designId: s.designId, artifactKey: s.artifactKey });
    expect(got[0]?.designId).toBe("job-1-d5");
    expect(got[0]?.artifactKey).toBe("orgs/org-1/jobs/job-1/designs/5.cif");
  });
});

describe("ModalProvider — error event", () => {
  it("translates {type:error} into a thrown Error with code", async () => {
    const logger = mkLogger();
    const fetchMock = mkFetchRouter({
      "/spawn": async () => jsonResponse({ call_id: "call-err" }),
      "/stream": async () =>
        ndjsonStream([
          JSON.stringify({ type: "seed", seed: 1, metrics: {} }),
          JSON.stringify({
            type: "error",
            code: "GPU_PREEMPT",
            message: "preempted",
            retryable: true,
          }),
        ]),
    });
    const client = new ModalClient({
      tokenId: "id",
      tokenSecret: "secret",
      baseUrl: "https://api.modal.test",
      backoffMs: 1,
      fetchImpl: fetchMock as unknown as typeof fetch,
    });
    const provider = new ModalProvider({
      logger,
      tokenId: "id",
      tokenSecret: "secret",
      client,
    });
    const result = await provider.spawnJob(
      mkManifest(),
      mkInputs({ numSeeds: 3 }),
    );

    const thrown = await (async () => {
      try {
        for await (const _s of result.seeds) {
          /* consume */
        }
        return null;
      } catch (e) {
        return e as Error & { code?: string; retryable?: boolean };
      }
    })();

    expect(thrown).not.toBeNull();
    expect(thrown?.code).toBe("GPU_PREEMPT");
    expect(thrown?.retryable).toBe(true);
  });
});

describe("ModalProvider — cancellation", () => {
  it("cancel() aborts the stream and POSTs cancel endpoint", async () => {
    const logger = mkLogger();
    let cancelPosted = false;

    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes("/spawn"))
        return jsonResponse({ call_id: "call-cancel" });
      if (url.includes("/stream")) {
        // Emit one seed, then close the controller when the abort signal fires
        // so the reader terminates naturally.
        let ctrl: ReadableStreamDefaultController<Uint8Array>;
        const stream = new ReadableStream<Uint8Array>({
          start(c) {
            ctrl = c;
            c.enqueue(
              new TextEncoder().encode(
                JSON.stringify({
                  type: "seed",
                  seed: 1,
                  metrics: { ipsae: 0.8 },
                }) + "\n",
              ),
            );
          },
        });
        const signal = init?.signal;
        if (signal) {
          signal.addEventListener("abort", () => {
            try {
              ctrl.close();
            } catch {
              /* ignore */
            }
          });
        }
        return new Response(stream, {
          status: 200,
          headers: { "content-type": "application/x-ndjson" },
        });
      }
      if (url.includes("/cancel")) {
        cancelPosted = true;
        return new Response(null, { status: 204 });
      }
      return new Response("not found", { status: 404 });
    });

    const client = new ModalClient({
      tokenId: "id",
      tokenSecret: "secret",
      baseUrl: "https://api.modal.test",
      backoffMs: 1,
      fetchImpl: fetchMock as unknown as typeof fetch,
    });
    const provider = new ModalProvider({
      logger,
      tokenId: "id",
      tokenSecret: "secret",
      client,
    });
    const result = await provider.spawnJob(
      mkManifest(),
      mkInputs({ numSeeds: 5 }),
    );

    // Consume the first seed, then cancel.
    const iter = result.seeds[Symbol.asyncIterator]();
    const first = await iter.next();
    expect(first.done).toBe(false);
    await result.cancel();

    // After cancel, draining should end; we swallow any AbortError.
    let drained = 0;
    try {
      while (true) {
        const n = await iter.next();
        if (n.done) break;
        drained += 1;
      }
    } catch {
      /* AbortError acceptable */
    }
    expect(drained).toBeLessThan(5);
    expect(cancelPosted).toBe(true);
  });
});

describe("ModalProvider — infra retry (503)", () => {
  it("retries transient 503 on spawn and succeeds", async () => {
    const logger = mkLogger();
    let spawnCalls = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/spawn")) {
        spawnCalls += 1;
        if (spawnCalls < 3) return new Response("unavailable", { status: 503 });
        return jsonResponse({ call_id: "call-retry" });
      }
      if (url.includes("/stream")) {
        return ndjsonStream([
          JSON.stringify({ type: "seed", seed: 1, metrics: {} }),
          JSON.stringify({ type: "done" }),
        ]);
      }
      return new Response("not found", { status: 404 });
    });
    const client = new ModalClient({
      tokenId: "id",
      tokenSecret: "secret",
      baseUrl: "https://api.modal.test",
      backoffMs: 1,
      maxRetries: 3,
      fetchImpl: fetchMock as unknown as typeof fetch,
    });
    const provider = new ModalProvider({
      logger,
      tokenId: "id",
      tokenSecret: "secret",
      client,
    });
    const result = await provider.spawnJob(
      mkManifest(),
      mkInputs({ numSeeds: 1 }),
    );
    expect(result.spawnId).toBe("call-retry");
    const seeds: number[] = [];
    for await (const s of result.seeds) seeds.push(s.seed);
    expect(seeds).toEqual([1]);
    expect(spawnCalls).toBe(3);
  });

  it("surfaces ModalHttpError after retries exhausted so worker can mark infra-error", async () => {
    const logger = mkLogger();
    const fetchMock = vi.fn(async () => new Response("down", { status: 503 }));
    const client = new ModalClient({
      tokenId: "id",
      tokenSecret: "secret",
      baseUrl: "https://api.modal.test",
      backoffMs: 1,
      maxRetries: 2,
      fetchImpl: fetchMock as unknown as typeof fetch,
    });
    const provider = new ModalProvider({
      logger,
      tokenId: "id",
      tokenSecret: "secret",
      client,
    });
    await expect(provider.spawnJob(mkManifest(), mkInputs())).rejects.toThrow(
      /503/,
    );
  });
});

describe("ModalProvider — function resolution", () => {
  it("maps tool_id to the correct Modal function URL", async () => {
    const logger = mkLogger();
    const seen: string[] = [];
    const fetchMock = vi.fn(async (url: string) => {
      seen.push(url);
      if (url.includes("/spawn")) return jsonResponse({ call_id: "call-map" });
      return ndjsonStream([JSON.stringify({ type: "done" })]);
    });
    const client = new ModalClient({
      tokenId: "id",
      tokenSecret: "secret",
      baseUrl: "https://api.modal.test",
      backoffMs: 1,
      fetchImpl: fetchMock as unknown as typeof fetch,
    });
    const provider = new ModalProvider({
      logger,
      tokenId: "id",
      tokenSecret: "secret",
      client,
    });

    const manifest = mkManifest({ id: "rfdiffusion", version: "1.2.3" });
    const result = await provider.spawnJob(manifest, mkInputs({ numSeeds: 1 }));
    for await (const _s of result.seeds) {
      /* consume */
    }
    const spawnUrl = seen.find((u) => u.includes("/spawn"));
    expect(spawnUrl).toContain("papercrane-prod/rfdiffusion/spawn");
    expect(spawnUrl).toContain("version=1");
  });
});

describe("ModalProvider.cancelJob / getCost", () => {
  it("cancelJob POSTs Modal cancel endpoint when client is present", async () => {
    const logger = mkLogger();
    let cancelled = false;
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/cancel")) {
        cancelled = true;
        return new Response(null, { status: 204 });
      }
      return new Response("not found", { status: 404 });
    });
    const client = new ModalClient({
      tokenId: "id",
      tokenSecret: "secret",
      baseUrl: "https://api.modal.test",
      backoffMs: 1,
      fetchImpl: fetchMock as unknown as typeof fetch,
    });
    const provider = new ModalProvider({
      logger,
      tokenId: "id",
      tokenSecret: "secret",
      client,
    });
    await provider.cancelJob("call-xyz");
    expect(cancelled).toBe(true);
  });

  it("cancelJob is a no-op log when falling back to stub (no tokens)", async () => {
    const logger = mkLogger();
    const provider = new ModalProvider({ logger });
    await expect(provider.cancelJob("call-xyz")).resolves.toBeUndefined();
  });

  it("getCost returns per-seed estimate", async () => {
    const logger = mkLogger();
    const provider = new ModalProvider({ logger });
    const q = await provider.getCost(mkInputs({ numSeeds: 10 }));
    expect(q.usd).toBeCloseTo(0.004);
  });

  it("fails closed before CLI dispatch when object storage is not configured", async () => {
    const logger = mkLogger();
    const provider = new ModalProvider({
      logger,
      tokenId: "real-cli-token-id",
      tokenSecret: "real-cli-token-secret",
    });
    await expect(
      provider.spawnJob(undefined, mkInputs({ toolId: "bindcraft" })),
    ).rejects.toMatchObject({
      code: "RUNTIME_ERROR",
    });
  });
});
