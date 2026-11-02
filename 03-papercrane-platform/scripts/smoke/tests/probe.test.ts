import { describe, expect, it, vi } from 'vitest';

import { assertExpected, joinUrl, probeRoute, waitForReady } from '../src/probe.js';
import type { RouteSpec } from '../src/routes.js';

const landing: RouteSpec = {
  id: 'landing',
  method: 'GET',
  path: '/',
  expected: {
    statuses: [200],
    bodyContains: ['Paper Crane'],
  },
  notes: 'landing page',
};

const securityTxt: RouteSpec = {
  id: 'security-txt',
  method: 'GET',
  path: '/.well-known/security.txt',
  expected: {
    statuses: [200],
    contentTypePrefix: 'text/plain',
  },
  notes: 'rfc 9116',
};

function makeResponse({
  status = 200,
  body = '',
  contentType = 'text/html; charset=utf-8',
}: {
  status?: number;
  body?: string;
  contentType?: string;
} = {}): Response {
  return new Response(body, {
    status,
    headers: { 'content-type': contentType },
  });
}

describe('joinUrl', () => {
  it('handles trailing slashes on base', () => {
    expect(joinUrl('http://127.0.0.1:3002/', '/foo')).toBe('http://127.0.0.1:3002/foo');
    expect(joinUrl('http://127.0.0.1:3002///', 'foo')).toBe('http://127.0.0.1:3002/foo');
  });

  it('adds a leading slash to the path when missing', () => {
    expect(joinUrl('http://a', 'b')).toBe('http://a/b');
  });
});

describe('assertExpected', () => {
  it('passes with matching status + body + content type', () => {
    expect(
      assertExpected(landing.expected, 200, 'text/html', '<h1>Paper Crane</h1>')
    ).toBeUndefined();
  });

  it('matches body substrings case-insensitively', () => {
    expect(
      assertExpected(landing.expected, 200, 'text/html', 'welcome to paper crane')
    ).toBeUndefined();
  });

  it('fails when status not in allowed list', () => {
    const reason = assertExpected(landing.expected, 404, 'text/html', 'Paper Crane');
    expect(reason).toMatch(/status 404 not in/);
  });

  it('fails when body substring missing on 2xx', () => {
    const reason = assertExpected(landing.expected, 200, 'text/html', 'nothing here');
    expect(reason).toMatch(/missing required substring/);
  });

  it('skips body assertions on non-2xx tolerated statuses', () => {
    const expected = { statuses: [200, 500], bodyContains: ['Paper Crane'] };
    expect(assertExpected(expected, 500, 'text/html', 'boom')).toBeUndefined();
  });

  it('fails when content-type prefix is wrong', () => {
    const reason = assertExpected(securityTxt.expected, 200, 'text/html', 'contact: x');
    expect(reason).toMatch(/content-type/);
  });

  it('handles missing content-type header', () => {
    const reason = assertExpected(securityTxt.expected, 200, undefined, 'contact: x');
    expect(reason).toMatch(/\(missing\)/);
  });
});

describe('probeRoute', () => {
  it('returns passed=true on a healthy response', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(makeResponse({ body: '<h1>Paper Crane launches</h1>' }));

    const result = await probeRoute('http://127.0.0.1:3002', landing, {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      sleepImpl: async () => {},
    });

    expect(result.passed).toBe(true);
    expect(result.status).toBe(200);
    expect(result.attempts).toBe(1);
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it('retries on network errors up to the configured limit', async () => {
    const sleepImpl = vi.fn().mockResolvedValue(undefined);
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new Error('ECONNREFUSED'))
      .mockRejectedValueOnce(new Error('ECONNREFUSED'))
      .mockResolvedValueOnce(makeResponse({ body: 'hello Paper Crane' }));

    const result = await probeRoute('http://127.0.0.1:3002', landing, {
      retries: 3,
      backoffMs: 1,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      sleepImpl,
    });

    expect(result.passed).toBe(true);
    expect(result.attempts).toBe(3);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    expect(sleepImpl).toHaveBeenCalledTimes(2);
  });

  it('gives up after retries are exhausted', async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new Error('ECONNREFUSED'));
    const result = await probeRoute('http://127.0.0.1:3002', landing, {
      retries: 2,
      backoffMs: 1,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      sleepImpl: async () => {},
    });

    expect(result.passed).toBe(false);
    expect(result.attempts).toBe(3);
    expect(result.failureReason).toMatch(/network error/);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it('does not retry on a clean-but-failing assertion', async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(makeResponse({ status: 404, body: 'nope' }));
    const result = await probeRoute('http://127.0.0.1:3002', landing, {
      retries: 3,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      sleepImpl: async () => {},
    });

    expect(result.passed).toBe(false);
    expect(result.status).toBe(404);
    // Only one fetch call — we got a clean HTTP answer so retrying is pointless.
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('tolerates a 500 response when the route declares it as acceptable', async () => {
    const leaderboard: RouteSpec = {
      id: 'leaderboard',
      method: 'GET',
      path: '/leaderboard',
      expected: { statuses: [200, 500] },
      notes: 'empty-state fallback accepted',
    };
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(makeResponse({ status: 500, body: 'Internal Error' }));

    const result = await probeRoute('http://127.0.0.1:3002', leaderboard, {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      sleepImpl: async () => {},
    });

    expect(result.passed).toBe(true);
    expect(result.status).toBe(500);
  });

  it('asserts content-type prefix for text/plain routes', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response('Contact: security@papercrane', {
        status: 200,
        headers: { 'content-type': 'text/plain; charset=utf-8' },
      })
    );
    const result = await probeRoute('http://127.0.0.1:3002', securityTxt, {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      sleepImpl: async () => {},
    });

    expect(result.passed).toBe(true);
    expect(result.contentType).toMatch(/^text\/plain/);
  });

  it('fails a text/plain route served as html', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response('<html>oops</html>', {
        status: 200,
        headers: { 'content-type': 'text/html' },
      })
    );
    const result = await probeRoute('http://127.0.0.1:3002', securityTxt, {
      fetchImpl: fetchImpl as unknown as typeof fetch,
      sleepImpl: async () => {},
    });

    expect(result.passed).toBe(false);
    expect(result.failureReason).toMatch(/content-type/);
  });
});

describe('waitForReady', () => {
  it('returns once fetch resolves', async () => {
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new Error('refused'))
      .mockResolvedValueOnce(new Response(null, { status: 500 }));
    const sleepImpl = vi.fn().mockResolvedValue(undefined);

    await waitForReady('http://127.0.0.1:3002', {
      maxWaitMs: 10_000,
      intervalMs: 1,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      sleepImpl,
    });

    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it('throws after exhausting the deadline', async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new Error('refused'));

    await expect(
      waitForReady('http://127.0.0.1:3002', {
        maxWaitMs: 5,
        intervalMs: 1,
        fetchImpl: fetchImpl as unknown as typeof fetch,
        sleepImpl: async () => {},
      })
    ).rejects.toThrow(/server not ready/);
  });
});
