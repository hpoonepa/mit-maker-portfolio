/**
 * Wave 8 / Agent 4 — focused ModalProvider unit tests.
 *
 * Complements the broader suite at `apps/worker/tests/providers/modal.test.ts`
 * by drilling into the four behaviors required by the Wave 8 brief:
 *   1. Stub fallback emits a synthetic NDJSON-equivalent seed stream when
 *      MODAL_TOKEN_ID is missing.
 *   2. Real path constructs the correct Modal Function URL & payload from the
 *      job spec (the closest analogue to "CLI args" — Modal has no CLI hop in
 *      this provider; we hit the HTTP API directly).
 *   3. NDJSON parser tolerates partial chunks, blank lines, malformed JSON,
 *      and a trailing line with no newline at end-of-stream.
 *   4. Job timeout fires its abort signal, terminating the in-flight stream.
 */

import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest';
import { ModalProvider } from '../modal';
import { ModalClient } from '../modalClient';
import type { ToolManifest } from '@papercrane/tools-sdk';
import type { ProviderSpawnInputs } from '../types';

// `resolveModalFunction()` reads MODAL_WORKSPACE at call time. Pin it so the
// URL assertion below (`papercrane-prod/...`) keeps working under the new
// env-driven default.
beforeAll(() => {
  vi.stubEnv('MODAL_WORKSPACE', 'papercrane-prod');
});
afterAll(() => {
  vi.unstubAllEnvs();
});

// ---------- shared fixtures ----------

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
  return logger as unknown as import('@papercrane/observability').Logger & {
    info: ReturnType<typeof vi.fn>;
    warn: ReturnType<typeof vi.fn>;
  };
}

function mkManifest(overrides: Partial<ToolManifest> = {}): ToolManifest {
  return {
    id: 'bindcraft',
    displayName: 'BindCraft',
    version: '1.0.0',
    adapterVersion: '1',
    category: 'binder_design',
    tier: 'open',
    license: 'MIT',
    image: 'papercrane/bindcraft',
    imageDigest: 'sha256:0',
    compute: {
      gpu: 'A100',
      gpuCount: 1,
      cpuCores: 8,
      memoryGb: 32,
      estSecondsPerDesign: 1, // small so timeoutMs is small in tests
    },
    ...overrides,
  };
}

function mkInputs(overrides: Partial<ProviderSpawnInputs> = {}): ProviderSpawnInputs {
  return {
    jobId: 'job-w8',
    orgId: 'org-w8',
    toolId: 'bindcraft',
    tier: 'pro',
    numSeeds: 2,
    request: { targetPdb: 'r2://target.pdb', hotspots: ['A12', 'A34'] },
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

// ---------- 1. Stub fallback (no Modal tokens) ----------

describe('ModalProvider stub fallback (MODAL_TOKEN_ID missing)', () => {
  it('warns once on construction and emits a synthetic seed stream', async () => {
    const logger = mkLogger();
    // Construct without tokenId / tokenSecret → falls back to stub.
    const provider = new ModalProvider({ logger, seedIntervalMs: 1 });

    expect(logger.warn).toHaveBeenCalledTimes(1);

    const result = await provider.spawnJob(mkManifest(), mkInputs({ numSeeds: 3 }));

    // spawnId is the stub marker — proves we did NOT hit any Modal endpoint.
    expect(result.spawnId).toBe('modal-stub-job-w8');

    const collected: Array<{ seed: number; designId: string; artifactKey: string }> = [];
    for await (const s of result.seeds) {
      collected.push({ seed: s.seed, designId: s.designId, artifactKey: s.artifactKey });
      // Each stub seed must populate the Provider contract.
      expect(typeof s.metrics.ipsae).toBe('number');
      expect(typeof s.metrics.iptm).toBe('number');
      expect(typeof s.metrics.plddt).toBe('number');
    }
    expect(collected.map((c) => c.seed)).toEqual([1, 2, 3]);
    expect(collected[0]?.designId).toBe('job-w8-d1');
    expect(collected[0]?.artifactKey).toBe('orgs/org-w8/jobs/job-w8/designs/1.cif');
  });

  it('stub stream stops mid-iteration when cancel() is called', async () => {
    const logger = mkLogger();
    const provider = new ModalProvider({ logger, seedIntervalMs: 5 });
    const result = await provider.spawnJob(mkManifest(), mkInputs({ numSeeds: 50 }));

    const iter = result.seeds[Symbol.asyncIterator]();
    const first = await iter.next();
    expect(first.done).toBe(false);
    await result.cancel();
    // Drain the rest — should terminate without emitting all 50 seeds.
    let count = 1;
    while (true) {
      const n = await iter.next();
      if (n.done) break;
      count += 1;
      if (count > 50) throw new Error('cancel did not stop stub stream');
    }
    expect(count).toBeLessThan(50);
  });
});

// ---------- 2. Real path constructs correct request from job spec ----------

describe('ModalProvider real path — request construction', () => {
  it('builds correct Function URL, version query, payload, and timeout', async () => {
    const logger = mkLogger();
    const seenUrls: string[] = [];
    const seenBodies: string[] = [];
    const seenHeaders: Array<Record<string, string>> = [];

    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      seenUrls.push(url);
      if (init?.body) seenBodies.push(init.body as string);
      if (init?.headers) {
        const h: Record<string, string> = {};
        for (const [k, v] of Object.entries(init.headers as Record<string, string>)) {
          h[k.toLowerCase()] = String(v);
        }
        seenHeaders.push(h);
      }
      if (url.includes('/spawn')) return jsonResponse({ call_id: 'call-construct' });
      if (url.includes('/stream')) {
        return new Response(JSON.stringify({ type: 'done' }) + '\n', {
          status: 200,
          headers: { 'content-type': 'application/x-ndjson' },
        });
      }
      return new Response('not found', { status: 404 });
    });

    const client = new ModalClient({
      tokenId: 'tok-id',
      tokenSecret: 'tok-secret',
      baseUrl: 'https://api.modal.test',
      backoffMs: 1,
      fetchImpl: fetchMock as unknown as typeof fetch,
    });
    const provider = new ModalProvider({
      logger,
      tokenId: 'tok-id',
      tokenSecret: 'tok-secret',
      client,
    });

    const manifest = mkManifest({
      id: 'rfdiffusion',
      version: '2.5.1',
      compute: {
        gpu: 'A100',
        gpuCount: 1,
        cpuCores: 8,
        memoryGb: 32,
        estSecondsPerDesign: 7,
      },
    });
    const inputs = mkInputs({
      jobId: 'job-construct',
      orgId: 'org-construct',
      tier: 'frontier',
      numSeeds: 4,
      request: { targetPdb: 'r2://x.pdb', hotspots: ['A1'] },
    });

    const result = await provider.spawnJob(manifest, inputs);

    // estimatedSeconds = secsPerDesign(7) * numSeeds(4) = 28
    expect(result.estimatedSeconds).toBe(28);
    expect(result.spawnId).toBe('call-construct');

    // Drain stream so cleanup runs.
    for await (const _ of result.seeds) {
      /* none */
    }

    // URL: workspace/name/spawn with major-version query param.
    const spawnUrl = seenUrls.find((u) => u.includes('/spawn'))!;
    expect(spawnUrl).toBe(
      'https://api.modal.test/v1/functions/papercrane-prod/rfdiffusion/spawn?version=2',
    );

    // Auth headers must be set with Modal-specific keys, never on the URL.
    const spawnHeaders = seenHeaders[0]!;
    expect(spawnHeaders['modal-key']).toBe('tok-id');
    expect(spawnHeaders['modal-secret']).toBe('tok-secret');
    expect(spawnHeaders['content-type']).toContain('application/json');
    expect(spawnUrl).not.toContain('tok-secret');

    // Body: input from job spec + timeout = estimatedSeconds * 2.
    const body = JSON.parse(seenBodies[0]!) as {
      input: Record<string, unknown>;
      timeout_seconds: number;
    };
    expect(body.timeout_seconds).toBe(56); // 28 * 2
    expect(body.input).toEqual({
      job_id: 'job-construct',
      org_id: 'org-construct',
      tier: 'frontier',
      num_seeds: 4,
      request: { targetPdb: 'r2://x.pdb', hotspots: ['A1'] },
    });
  });

  it('throws when manifest is missing on the real (non-stub) path', async () => {
    const logger = mkLogger();
    const client = new ModalClient({
      tokenId: 'id',
      tokenSecret: 'secret',
      baseUrl: 'https://api.modal.test',
      fetchImpl: vi.fn() as unknown as typeof fetch,
    });
    const provider = new ModalProvider({ logger, tokenId: 'id', tokenSecret: 'secret', client });
    await expect(
      provider.spawnJob(undefined, mkInputs()),
    ).rejects.toThrow(/requires a ToolManifest/);
  });
});

// ---------- 3. NDJSON parser robustness ----------

describe('ModalClient NDJSON stream parsing', () => {
  /**
   * Build a Response whose body is a ReadableStream that emits the supplied
   * chunks in order. Lets us simulate partial/split frames the same way the
   * real Modal stream does.
   */
  function chunkedStream(chunks: string[]): Response {
    const enc = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const c of chunks) controller.enqueue(enc.encode(c));
        controller.close();
      },
    });
    return new Response(stream, {
      status: 200,
      headers: { 'content-type': 'application/x-ndjson' },
    });
  }

  it('reassembles seed events split across chunk boundaries', async () => {
    const fetchMock = vi.fn(async () =>
      chunkedStream([
        // First event split across two chunks
        '{"type":"seed","seed":1,"metr',
        'ics":{"ipsae":0.81}}\n',
        // Second event arrives whole
        '{"type":"seed","seed":2,"metrics":{"ipsae":0.7}}\n',
        '{"type":"done"}\n',
      ]),
    );
    const client = new ModalClient({
      tokenId: 'id',
      tokenSecret: 'secret',
      baseUrl: 'https://api.modal.test',
      fetchImpl: fetchMock as unknown as typeof fetch,
    });

    const events: unknown[] = [];
    for await (const evt of client.streamCall('call-1')) events.push(evt);

    expect(events).toEqual([
      { type: 'seed', seed: 1, metrics: { ipsae: 0.81 } },
      { type: 'seed', seed: 2, metrics: { ipsae: 0.7 } },
      { type: 'done' },
    ]);
  });

  it('skips malformed JSON lines and blank lines without aborting the stream', async () => {
    const onRawLine = vi.fn();
    const fetchMock = vi.fn(async () =>
      chunkedStream([
        '\n', // blank line — must be ignored
        '{"type":"seed","seed":1,"metrics":{}}\n',
        'not-json-at-all\n', // malformed — must be skipped, not thrown
        '{"type":"seed","seed":2,"metrics":{}}\n',
        '{"type":"done"}\n',
      ]),
    );
    const client = new ModalClient({
      tokenId: 'id',
      tokenSecret: 'secret',
      baseUrl: 'https://api.modal.test',
      fetchImpl: fetchMock as unknown as typeof fetch,
    });

    const events: unknown[] = [];
    for await (const evt of client.streamCall('c', { onRawLine })) events.push(evt);

    expect(events).toEqual([
      { type: 'seed', seed: 1, metrics: {} },
      { type: 'seed', seed: 2, metrics: {} },
      { type: 'done' },
    ]);
    // onRawLine still saw the malformed text — useful for debug forwarding.
    const rawLines = onRawLine.mock.calls.map((c) => c[0] as string);
    expect(rawLines).toContain('not-json-at-all');
  });

  it('flushes a trailing line that has no terminating newline at end-of-stream', async () => {
    const fetchMock = vi.fn(async () =>
      chunkedStream([
        '{"type":"seed","seed":1,"metrics":{}}\n',
        // Final event arrives without a trailing newline — must still be parsed.
        '{"type":"done"}',
      ]),
    );
    const client = new ModalClient({
      tokenId: 'id',
      tokenSecret: 'secret',
      baseUrl: 'https://api.modal.test',
      fetchImpl: fetchMock as unknown as typeof fetch,
    });

    const events: unknown[] = [];
    for await (const evt of client.streamCall('c')) events.push(evt);
    expect(events).toEqual([
      { type: 'seed', seed: 1, metrics: {} },
      { type: 'done' },
    ]);
  });

  it('strips SSE-style `data:` framing for forward-compat', async () => {
    const fetchMock = vi.fn(async () =>
      chunkedStream([
        'data: {"type":"seed","seed":1,"metrics":{}}\n',
        'data: {"type":"done"}\n',
      ]),
    );
    const client = new ModalClient({
      tokenId: 'id',
      tokenSecret: 'secret',
      baseUrl: 'https://api.modal.test',
      fetchImpl: fetchMock as unknown as typeof fetch,
    });
    const events: unknown[] = [];
    for await (const evt of client.streamCall('c')) events.push(evt);
    expect(events).toEqual([
      { type: 'seed', seed: 1, metrics: {} },
      { type: 'done' },
    ]);
  });
});

// ---------- 4. Job timeout aborts the spawned process ----------

describe('ModalProvider job timeout', () => {
  it('aborts the in-flight stream when the wall-clock budget is exceeded', async () => {
    vi.useFakeTimers();
    try {
      const logger = mkLogger();
      let abortFired = false;
      let streamSignal: AbortSignal | undefined;

      const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
        if (url.includes('/spawn')) {
          return jsonResponse({ call_id: 'call-timeout' });
        }
        if (url.includes('/stream')) {
          streamSignal = init?.signal ?? undefined;
          // Build a stream that emits one seed and then waits indefinitely. The
          // controller is closed only when the abort signal fires — that's the
          // path under test.
          let ctrl: ReadableStreamDefaultController<Uint8Array>;
          const stream = new ReadableStream<Uint8Array>({
            start(c) {
              ctrl = c;
              c.enqueue(
                new TextEncoder().encode(
                  JSON.stringify({ type: 'seed', seed: 1, metrics: { ipsae: 0.5 } }) + '\n',
                ),
              );
            },
          });
          if (streamSignal) {
            streamSignal.addEventListener('abort', () => {
              abortFired = true;
              try {
                ctrl.close();
              } catch {
                /* ignore */
              }
            });
          }
          return new Response(stream, {
            status: 200,
            headers: { 'content-type': 'application/x-ndjson' },
          });
        }
        if (url.includes('/cancel')) return new Response(null, { status: 204 });
        return new Response('not found', { status: 404 });
      });

      const client = new ModalClient({
        tokenId: 'id',
        tokenSecret: 'secret',
        baseUrl: 'https://api.modal.test',
        backoffMs: 1,
        fetchImpl: fetchMock as unknown as typeof fetch,
      });
      const provider = new ModalProvider({
        logger,
        tokenId: 'id',
        tokenSecret: 'secret',
        client,
      });

      // estSecondsPerDesign=1, numSeeds=2 → timeout is 1*2*2*1000 = 4000ms.
      const result = await provider.spawnJob(mkManifest(), mkInputs({ numSeeds: 2 }));

      const iter = result.seeds[Symbol.asyncIterator]();
      const first = await iter.next();
      expect(first.done).toBe(false);

      // Trip the timer — must fire abort on the spawned stream.
      await vi.advanceTimersByTimeAsync(5_000);
      expect(abortFired).toBe(true);
      expect(streamSignal?.aborted).toBe(true);

      // Drain — we tolerate either a clean end or an AbortError.
      try {
        while (true) {
          const n = await iter.next();
          if (n.done) break;
        }
      } catch {
        /* AbortError acceptable */
      }
      // Logger surface lets ops see the timeout reason.
      expect(logger.warn).toHaveBeenCalledWith(
        expect.objectContaining({ callId: 'call-timeout' }),
        expect.stringContaining('timed out'),
      );
    } finally {
      vi.useRealTimers();
    }
  });
});
