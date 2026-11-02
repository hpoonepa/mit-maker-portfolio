import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

/**
 * Tests for `apps/app/middleware.ts`.
 *
 * Behaviour under test:
 *   1. /app/* with no user -> 307 redirect to /login?redirectTo=...
 *   2. /app/* with a user  -> pass-through (NextResponse.next)
 *   3. /login with a user  -> show sign-in, including the landing-page entry
 *   4. /login with no user -> pass-through
 *   5. Non-protected route -> pass-through even when unauthenticated
 *   6. Missing Supabase env on /app/* -> still redirects to /login (fail-safe)
 *   7. Missing Supabase env on a public route -> pass-through, no Supabase
 *      client created (no env crash).
 *
 * We mock:
 *   - `next/server` (NextResponse.next/redirect, NextRequest constructor)
 *   - `@supabase/ssr` createServerClient (returns a fake auth.getUser)
 *
 * The aim is to exercise the routing logic without booting Next.js.
 */

// --- mocks -----------------------------------------------------------------

const nextSentinel = Symbol("NextResponse.next");

function makeResponseBase() {
  return {
    headers: new Headers(),
    cookies: { set: vi.fn() },
  };
}

const NextResponse = {
  next: vi.fn(() => ({ kind: nextSentinel, ...makeResponseBase() })),
  redirect: vi.fn((url: URL) => ({ kind: "redirect", url, ...makeResponseBase() })),
};

vi.mock("next/server", () => ({
  NextResponse,
  // The middleware only uses NextRequest as a type; the runtime uses our
  // hand-rolled fake below, so a no-op class is sufficient.
  NextRequest: class {},
}));

const getUserMock = vi.fn();
const createServerClientMock = vi.fn(() => ({
  auth: { getUser: getUserMock },
}));

vi.mock("@supabase/ssr", () => ({
  createServerClient: createServerClientMock,
}));

// --- helpers ---------------------------------------------------------------

interface FakeRequest {
  headers: Headers;
  cookies: {
    getAll: () => Array<{ name: string; value: string }>;
    set: (name: string, value: string) => void;
  };
  nextUrl: { pathname: string; search: string };
  url: string;
}

function makeRequest(pathname: string, search = ""): FakeRequest {
  return {
    headers: new Headers(),
    cookies: {
      getAll: vi.fn(() => []),
      set: vi.fn(),
    },
    nextUrl: { pathname, search },
    url: `https://app.papercrane.bio${pathname}${search}`,
  };
}

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = "https://test.supabase.co";
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "anon-key";
  NextResponse.next.mockClear();
  NextResponse.redirect.mockClear();
  createServerClientMock.mockClear();
  getUserMock.mockReset();
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  vi.resetModules();
});

// --- tests -----------------------------------------------------------------

describe("middleware auth guard", () => {
  it("redirects unauthenticated users from /app/* to /login with redirectTo", async () => {
    getUserMock.mockResolvedValue({ data: { user: null } });
    const { middleware } = await import("../../middleware");
    const req = makeRequest("/app/jobs");

    const result = (await middleware(req as never)) as unknown as {
      kind: string;
      url: URL;
    };

    expect(result.kind).toBe("redirect");
    expect(result.url.pathname).toBe("/login");
    expect(result.url.searchParams.get("redirectTo")).toBe("/app/jobs");
    expect(NextResponse.redirect).toHaveBeenCalledTimes(1);
  });

  it("includes the original query string in redirectTo", async () => {
    getUserMock.mockResolvedValue({ data: { user: null } });
    const { middleware } = await import("../../middleware");
    const req = makeRequest("/app/jobs", "?status=running");

    const result = (await middleware(req as never)) as unknown as {
      kind: string;
      url: URL;
    };

    expect(result.url.searchParams.get("redirectTo")).toBe(
      "/app/jobs?status=running"
    );
  });

  it("allows authenticated users through to /app/*", async () => {
    getUserMock.mockResolvedValue({
      data: { user: { id: "u1", email: "u@x.com" } },
    });
    const { middleware } = await import("../../middleware");
    const req = makeRequest("/app/dashboard");

    const result = (await middleware(req as never)) as unknown as { kind: symbol };
    expect(result.kind).toBe(nextSentinel);
    expect(NextResponse.redirect).not.toHaveBeenCalled();
  });

  it("shows sign-in even when the landing visitor has an existing session", async () => {
    getUserMock.mockResolvedValue({
      data: { user: { id: "u1", email: "u@x.com" } },
    });
    const { middleware } = await import("../../middleware");
    const req = makeRequest("/login", "?redirectTo=%2Fapp");

    const result = (await middleware(req as never)) as unknown as { kind: symbol };
    expect(result.kind).toBe(nextSentinel);
    expect(NextResponse.redirect).not.toHaveBeenCalled();
  });

  it("lets unauthenticated visitors view /login", async () => {
    getUserMock.mockResolvedValue({ data: { user: null } });
    const { middleware } = await import("../../middleware");
    const req = makeRequest("/login");

    const result = (await middleware(req as never)) as unknown as { kind: symbol };
    expect(result.kind).toBe(nextSentinel);
    expect(NextResponse.redirect).not.toHaveBeenCalled();
  });

  it("allows unauthenticated traffic on public marketing routes", async () => {
    getUserMock.mockResolvedValue({ data: { user: null } });
    const { middleware } = await import("../../middleware");
    const req = makeRequest("/pricing");

    const result = (await middleware(req as never)) as unknown as { kind: symbol };
    expect(result.kind).toBe(nextSentinel);
    expect(NextResponse.redirect).not.toHaveBeenCalled();
  });

  it("fail-safe: missing Supabase env still redirects /app/* to /login", async () => {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    const { middleware } = await import("../../middleware");
    const req = makeRequest("/app/anything");

    const result = (await middleware(req as never)) as unknown as {
      kind: string;
      url: URL;
    };

    expect(result.kind).toBe("redirect");
    expect(result.url.pathname).toBe("/login");
    expect(createServerClientMock).not.toHaveBeenCalled();
  });

  it("fail-safe: missing Supabase env passes through public routes", async () => {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    const { middleware } = await import("../../middleware");
    const req = makeRequest("/");

    const result = (await middleware(req as never)) as unknown as { kind: symbol };
    expect(result.kind).toBe(nextSentinel);
    expect(createServerClientMock).not.toHaveBeenCalled();
    expect(NextResponse.redirect).not.toHaveBeenCalled();
  });

  it("allows Molstar to fetch signed design structures from R2", async () => {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    const { middleware } = await import("../../middleware");

    const result = (await middleware(
      makeRequest("/") as never,
    )) as unknown as ReturnType<typeof makeResponseBase>;
    const csp = result.headers.get("Content-Security-Policy") ?? "";
    const connectSrc =
      csp
        .split("; ")
        .find((directive) => directive.startsWith("connect-src ")) ?? "";

    expect(connectSrc).toContain("https://*.r2.cloudflarestorage.com");
  });
});


describe("middleware API CSP", () => {
  it("allows the API_BASE_URL public alias used by the browser client", async () => {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://api.alias.example/v1";
    process.env.NEXT_PUBLIC_API_URL = "https://other.example";
    const { middleware } = await import("../../middleware");
    const result = await middleware(makeRequest("/") as never);
    const connectSrc = result.headers.get("Content-Security-Policy")?.split("; ").find(value => value.startsWith("connect-src "));
    expect(connectSrc).toContain("https://api.alias.example");
    expect(connectSrc).not.toContain("https://api.alias.example/v1");
    expect(connectSrc).not.toContain("https://other.example");
  });
  it("allows canonical API in production with no configured API alias", async () => {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    delete process.env.NEXT_PUBLIC_API_URL;
    vi.stubEnv("NODE_ENV", "production");
    const { middleware } = await import("../../middleware");
    const result = await middleware(makeRequest("/") as never);
    const connectSrc = result.headers.get("Content-Security-Policy")?.split("; ").find(value => value.startsWith("connect-src "));
    expect(connectSrc).toContain("https://api.papercrane.bio");
    expect(connectSrc).not.toContain("localhost");
    vi.unstubAllEnvs();
  });
});
