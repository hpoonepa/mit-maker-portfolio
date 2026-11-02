/**
 * ModalClient tests — spawn, stream, cancel, cost, retry policy.
 *
 * We mock fetch directly (MSW isn't in the workspace dep tree; adding it would
 * violate the "no new packages" constraint for this task). The mock returns
 * real `Response` objects so streaming/header semantics match production.
 */

import { describe, it, expect, vi } from 'vitest';
import { ModalClient, ModalHttpError } from '../../src/providers/modalClient';
import type { ModalFunctionRef } from '../../src/providers/modalFunctionMap';

const fn: ModalFunctionRef = {
  workspace: 'papercrane-prod',
  name: 'bindcraft',
  appName: 'papercrane-bindcraft',
  entrypoint: 'papercrane_dispatch',
  returnsEvents: false,
  version: '1',
};

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
    ...init,
  });
}

function ndjsonResponse(lines: string[], init: ResponseInit = {}): Response {
  const body = lines.join('\n') + '\n';
  return new Response(body, {
    status: 200,
    headers: { 'content-type': 'application/x-ndjson' },
    ...init,
  });
}

function mkClient(fetchImpl: typeof fetch, overrides: Partial<ConstructorParameters<typeof ModalClient>[0]> = {}) {
  return new ModalClient({
    tokenId: 'id-xxx',
    tokenSecret: 'secret-yyy',
    baseUrl: 'https://api.modal.test',
    backoffMs: 1,
    fetchImpl,
    ...overrides,
  });
}

describe('ModalClient.spawnCall', () => {
  it('POSTs the spawn endpoint and returns call_id', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      expect(url).toBe(
        'https://api.modal.test/v1/functions/papercrane-prod/bindcraft/spawn?version=1',
      );
      expect(init?.method).toBe('POST');
      const headers = init?.headers as Record<string, string>;
      expect(headers['Modal-Key']).toBe('id-xxx');
      expect(headers['Modal-Secret']).toBe('secret-yyy');
      expect(init?.body).toContain('"input"');
      return jsonResponse({ call_id: 'call-123' });
    });
    const client = mkClient(fetchMock as unknown as typeof fetch);
    const res = await client.spawnCall({ fn, input: { seeds: 3 } });
    expect(res.callId).toBe('call-123');
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('accepts camelCase callId in the response (forward-compat)', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ callId: 'call-camel' }));
    const client = mkClient(fetchMock as unknown as typeof fetch);
    const res = await client.spawnCall({ fn, input: {} });
    expect(res.callId).toBe('call-camel');
  });

  it('throws when response has no call_id', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({}));
    const client = mkClient(fetchMock as unknown as typeof fetch);
    await expect(client.spawnCall({ fn, input: {} })).rejects.toThrow(/call_id/);
  });
});

describe('ModalClient retry policy', () => {
  it('retries transient 503 up to maxRetries then succeeds', async () => {
    let calls = 0;
    const fetchMock = vi.fn(async () => {
      calls += 1;
      if (calls < 3) return new Response('unavailable', { status: 503 });
      return jsonResponse({ call_id: 'call-ok' });
    });
    const client = mkClient(fetchMock as unknown as typeof fetch, { maxRetries: 3 });
    const res = await client.spawnCall({ fn, input: {} });
    expect(res.callId).toBe('call-ok');
    expect(calls).toBe(3);
  });

  it('retries 429 with backoff and eventually surfaces ModalHttpError', async () => {
    let calls = 0;
    const fetchMock = vi.fn(async () => {
      calls += 1;
      return new Response('rate limited', { status: 429 });
    });
    const client = mkClient(fetchMock as unknown as typeof fetch, { maxRetries: 2 });
    await expect(client.spawnCall({ fn, input: {} })).rejects.toBeInstanceOf(ModalHttpError);
    // initial + 2 retries = 3 total
    expect(calls).toBe(3);
  });

  it('does NOT retry 4xx errors (other than 429)', async () => {
    let calls = 0;
    const fetchMock = vi.fn(async () => {
      calls += 1;
      return new Response('bad input', { status: 400 });
    });
    const client = mkClient(fetchMock as unknown as typeof fetch, { maxRetries: 3 });
    const err = await client.spawnCall({ fn, input: {} }).catch((e) => e);
    expect(err).toBeInstanceOf(ModalHttpError);
    expect((err as ModalHttpError).status).toBe(400);
    expect(calls).toBe(1);
  });
});

describe('ModalClient.streamCall', () => {
  it('parses NDJSON events in order', async () => {
    const fetchMock = vi.fn(async () =>
      ndjsonResponse([
        JSON.stringify({ type: 'log', message: 'starting' }),
        JSON.stringify({ type: 'seed', seed: 1, metrics: { ipsae: 0.8 } }),
        JSON.stringify({ type: 'seed', seed: 2, metrics: { ipsae: 0.7 } }),
        JSON.stringify({ type: 'done' }),
      ]),
    );
    const client = mkClient(fetchMock as unknown as typeof fetch);
    const events: unknown[] = [];
    for await (const evt of client.streamCall('call-xyz')) {
      events.push(evt);
    }
    expect(events).toEqual([
      { type: 'log', message: 'starting' },
      { type: 'seed', seed: 1, metrics: { ipsae: 0.8 } },
      { type: 'seed', seed: 2, metrics: { ipsae: 0.7 } },
      { type: 'done' },
    ]);
  });

  it('tolerates SSE-style "data:" prefixed lines', async () => {
    const fetchMock = vi.fn(async () =>
      ndjsonResponse([
        `data: ${JSON.stringify({ type: 'seed', seed: 1, metrics: {} })}`,
        `data: ${JSON.stringify({ type: 'done' })}`,
      ]),
    );
    const client = mkClient(fetchMock as unknown as typeof fetch);
    const events: unknown[] = [];
    for await (const evt of client.streamCall('call-xyz')) {
      events.push(evt);
    }
    expect(events).toHaveLength(2);
    expect((events[0] as { seed: number }).seed).toBe(1);
  });

  it('skips malformed JSON lines', async () => {
    const fetchMock = vi.fn(async () =>
      ndjsonResponse([
        'not-json',
        JSON.stringify({ type: 'seed', seed: 1, metrics: {} }),
      ]),
    );
    const client = mkClient(fetchMock as unknown as typeof fetch);
    const events: unknown[] = [];
    for await (const evt of client.streamCall('call-xyz')) events.push(evt);
    expect(events).toHaveLength(1);
  });

  it('aborts when signal is triggered', async () => {
    // Stream a first seed, then wait for the abort signal and close the
    // controller so the reader naturally terminates.
    const fetchMock = vi.fn(async (_url, init?: RequestInit) => {
      let ctrl: ReadableStreamDefaultController<Uint8Array>;
      const stream = new ReadableStream<Uint8Array>({
        start(c) {
          ctrl = c;
          c.enqueue(
            new TextEncoder().encode(
              JSON.stringify({ type: 'seed', seed: 1, metrics: {} }) + '\n',
            ),
          );
        },
      });
      const signal = init?.signal;
      if (signal) {
        signal.addEventListener('abort', () => {
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
    });
    const client = mkClient(fetchMock as unknown as typeof fetch);
    const ctl = new AbortController();
    const iter = client.streamCall('call-xyz', { signal: ctl.signal });

    const first = await iter.next();
    expect(first.done).toBe(false);
    ctl.abort();

    const rest: unknown[] = [];
    try {
      for await (const evt of iter) rest.push(evt);
    } catch {
      // AbortError is acceptable here.
    }
    expect(rest.length).toBe(0);
  });
});

describe('ModalClient.cancelCall', () => {
  it('POSTs the cancel endpoint', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      expect(url).toBe('https://api.modal.test/v1/calls/call-abc/cancel');
      expect(init?.method).toBe('POST');
      return new Response(null, { status: 204 });
    });
    const client = mkClient(fetchMock as unknown as typeof fetch);
    await client.cancelCall('call-abc');
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});

describe('ModalClient.getCost', () => {
  it('returns usd_cents / 100', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ usd_cents: 42 }));
    const client = mkClient(fetchMock as unknown as typeof fetch);
    const cost = await client.getCost('call-abc');
    expect(cost.usd).toBeCloseTo(0.42);
  });

  it('returns usd directly when present', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ usd: 1.23 }));
    const client = mkClient(fetchMock as unknown as typeof fetch);
    const cost = await client.getCost('call-abc');
    expect(cost.usd).toBe(1.23);
  });
});
