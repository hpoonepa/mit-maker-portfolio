/**
 * Routes probed by the smoke test.
 *
 * Each route has an `expected` predicate describing acceptable responses. The
 * runner counts a probe as passing when the predicate returns true. Several
 * Cross-app routes are expected to redirect from the marketing host to the
 * authenticated app. The smoke test runs without Supabase credentials, so it
 * verifies those boundaries without following the redirect.
 */

export type ExpectedOutcome = {
  /** Allowed HTTP status codes. */
  statuses: number[];
  /**
   * Optional body substring(s) that MUST appear for a 2xx response. Matching
   * is case-insensitive. Bodies are only checked when the status is 2xx; this
   * keeps the check meaningful when a route is allowed to legitimately 4xx/5xx.
   */
  bodyContains?: string[];
  /** Optional content-type prefix (case-insensitive). */
  contentTypePrefix?: string;
};

export type RouteSpec = {
  /** Stable identifier used in junit-xml output. */
  id: string;
  /** Request method. */
  method: 'GET' | 'POST' | 'HEAD';
  /** URL path, must start with "/". */
  path: string;
  /** Acceptable response shape. */
  expected: ExpectedOutcome;
  /**
   * Human-readable notes. Use this to document WHY a route is allowed to
   * degrade (e.g. no Supabase env in CI) so future regressions aren't masked.
   */
  notes: string;
};

export const ROUTES: RouteSpec[] = [
  {
    id: 'landing',
    method: 'GET',
    path: '/',
    expected: {
      statuses: [200],
      bodyContains: ['Paper Crane'],
    },
    notes: 'Landing page must always render and mention the brand.',
  },
  {
    id: 'leaderboard',
    method: 'GET',
    path: '/leaderboard',
    expected: {
      statuses: [307, 308],
    },
    notes:
      'The public leaderboard lives in the product app, so marketing must redirect without rendering a stale local copy.',
  },
  {
    id: 'security-txt',
    method: 'GET',
    path: '/.well-known/security.txt',
    expected: {
      statuses: [200],
      contentTypePrefix: 'text/plain',
    },
    notes: 'RFC 9116 security contact. Must be text/plain and stable.',
  },
  {
    id: 'login',
    method: 'GET',
    path: '/login',
    expected: {
      statuses: [307, 308],
    },
    notes:
      'Marketing delegates authentication to app.papercrane.bio and must redirect there without requiring Supabase credentials.',
  },
  {
    id: 'logout',
    method: 'GET',
    path: '/logout',
    expected: {
      statuses: [307, 308],
    },
    notes: 'Marketing delegates session termination to the product app logout route.',
  },
];

/**
 * Validates the routes table shape. Exposed so the unit test can assert that
 * the table stays well-formed if anyone edits it.
 */
export function validateRoutes(routes: RouteSpec[]): void {
  const seen = new Set<string>();
  for (const route of routes) {
    if (!route.id) throw new Error('route.id is required');
    if (seen.has(route.id)) throw new Error(`duplicate route id: ${route.id}`);
    seen.add(route.id);

    if (!route.path.startsWith('/')) {
      throw new Error(`route ${route.id} path must start with "/" (got ${route.path})`);
    }
    if (!['GET', 'POST', 'HEAD'].includes(route.method)) {
      throw new Error(`route ${route.id} has unsupported method ${route.method}`);
    }
    if (!route.expected.statuses.length) {
      throw new Error(`route ${route.id} must declare at least one expected status`);
    }
    for (const status of route.expected.statuses) {
      if (!Number.isInteger(status) || status < 100 || status >= 600) {
        throw new Error(`route ${route.id} has invalid status ${status}`);
      }
    }
    if (!route.notes) {
      throw new Error(`route ${route.id} must include human-readable notes`);
    }
  }
}
