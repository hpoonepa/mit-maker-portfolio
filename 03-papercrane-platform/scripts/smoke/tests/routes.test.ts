import { describe, expect, it } from 'vitest';

import { ROUTES, validateRoutes, type RouteSpec } from '../src/routes.js';

describe('routes table', () => {
  it('is well-formed', () => {
    expect(() => validateRoutes(ROUTES)).not.toThrow();
  });

  it('covers the critical regression routes', () => {
    const paths = new Set(ROUTES.map((r) => r.path));
    for (const required of ['/', '/leaderboard', '/login', '/logout', '/.well-known/security.txt']) {
      expect(paths, `missing required route ${required}`).toContain(required);
    }
  });

  it('uses unique ids', () => {
    const ids = ROUTES.map((r) => r.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('documents every route with notes', () => {
    for (const route of ROUTES) {
      expect(route.notes.length, `route ${route.id} needs notes`).toBeGreaterThan(10);
    }
  });

  it('rejects a duplicate id', () => {
    const bad: RouteSpec[] = [
      { id: 'dup', method: 'GET', path: '/a', expected: { statuses: [200] }, notes: 'a'.repeat(20) },
      { id: 'dup', method: 'GET', path: '/b', expected: { statuses: [200] }, notes: 'b'.repeat(20) },
    ];
    expect(() => validateRoutes(bad)).toThrow(/duplicate route id/);
  });

  it('rejects a path without a leading slash', () => {
    const bad: RouteSpec[] = [
      {
        id: 'noslash',
        method: 'GET',
        path: 'foo',
        expected: { statuses: [200] },
        notes: 'needs a leading slash',
      },
    ];
    expect(() => validateRoutes(bad)).toThrow(/must start with "\/"/);
  });

  it('rejects an invalid status code', () => {
    const bad: RouteSpec[] = [
      {
        id: 'bad-status',
        method: 'GET',
        path: '/x',
        expected: { statuses: [99] },
        notes: 'bogus status code',
      },
    ];
    expect(() => validateRoutes(bad)).toThrow(/invalid status/);
  });

  it('rejects an unsupported method', () => {
    const bad = [
      {
        id: 'weird',
        method: 'PATCH',
        path: '/x',
        expected: { statuses: [200] },
        notes: 'not supported',
      },
    ] as unknown as RouteSpec[];
    expect(() => validateRoutes(bad)).toThrow(/unsupported method/);
  });

  it('leaderboard redirects to the product app', () => {
    const leaderboard = ROUTES.find((r) => r.id === 'leaderboard');
    expect(leaderboard).toBeDefined();
    expect(leaderboard!.expected.statuses).toEqual([307, 308]);
  });

  it('login redirects without requiring Supabase env', () => {
    const login = ROUTES.find((r) => r.id === 'login');
    expect(login).toBeDefined();
    expect(login!.expected.statuses).toEqual([307, 308]);
  });

  it('security.txt asserts the text/plain content type', () => {
    const sec = ROUTES.find((r) => r.id === 'security-txt');
    expect(sec).toBeDefined();
    expect(sec!.expected.contentTypePrefix).toBe('text/plain');
  });
});
