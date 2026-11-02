import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

/**
 * Tests for `apps/app/lib/supabase/server.ts`.
 *
 * We mock:
 *   - `next/headers` -> cookies()  (Next runtime cookie store)
 *   - `@supabase/ssr` -> createServerClient (no real network)
 *
 * The tests verify:
 *   1. Throws when env vars are missing.
 *   2. Wires the cookie store's getAll into the Supabase client.
 *   3. setAll forwards cookies to cookieStore.set.
 *   4. setAll swallows errors thrown by a read-only RSC cookie store.
 *   5. getSessionUser returns the user when a session is present.
 *   6. getSessionUser returns null when no session is present.
 */

// --- module-level mocks ----------------------------------------------------

const cookieStoreMock = {
  getAll: vi.fn<() => Array<{ name: string; value: string }>>(() => []),
  set: vi.fn(),
};

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => cookieStoreMock),
}));

let capturedCookieAdapter:
  | {
      getAll: () => Array<{ name: string; value: string }>;
      setAll: (
        rows: Array<{ name: string; value: string; options: unknown }>
      ) => void;
    }
  | null = null;

const getUserMock = vi.fn();

vi.mock("@supabase/ssr", () => ({
  createServerClient: vi.fn(
    (
      _url: string,
      _key: string,
      opts: {
        cookies: {
          getAll: () => Array<{ name: string; value: string }>;
          setAll: (
            rows: Array<{ name: string; value: string; options: unknown }>
          ) => void;
        };
      }
    ) => {
      capturedCookieAdapter = opts.cookies;
      return {
        auth: {
          getUser: getUserMock,
        },
      };
    }
  ),
}));

// --- helpers ---------------------------------------------------------------

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = "https://test.supabase.co";
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "anon-key";
  cookieStoreMock.getAll.mockReset();
  cookieStoreMock.getAll.mockReturnValue([]);
  cookieStoreMock.set.mockReset();
  getUserMock.mockReset();
  capturedCookieAdapter = null;
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  vi.resetModules();
});

// --- tests -----------------------------------------------------------------

describe("createSupabaseServerClient", () => {
  it("throws when NEXT_PUBLIC_SUPABASE_URL is missing", async () => {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    const { createSupabaseServerClient } = await import("../supabase/server");
    await expect(createSupabaseServerClient()).rejects.toThrow(
      /Missing Supabase env/
    );
  });

  it("throws when NEXT_PUBLIC_SUPABASE_ANON_KEY is missing", async () => {
    delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    const { createSupabaseServerClient } = await import("../supabase/server");
    await expect(createSupabaseServerClient()).rejects.toThrow(
      /Missing Supabase env/
    );
  });

  it("wires getAll() to the Next cookie store", async () => {
    cookieStoreMock.getAll.mockReturnValue([
      { name: "sb-access-token", value: "abc" },
    ]);
    const { createSupabaseServerClient } = await import("../supabase/server");
    await createSupabaseServerClient();

    expect(capturedCookieAdapter).not.toBeNull();
    const all = capturedCookieAdapter!.getAll();
    expect(all).toEqual([{ name: "sb-access-token", value: "abc" }]);
    expect(cookieStoreMock.getAll).toHaveBeenCalled();
  });

  it("setAll forwards each cookie to cookieStore.set", async () => {
    const { createSupabaseServerClient } = await import("../supabase/server");
    await createSupabaseServerClient();

    capturedCookieAdapter!.setAll([
      { name: "a", value: "1", options: { path: "/" } },
      { name: "b", value: "2", options: { path: "/" } },
    ]);

    expect(cookieStoreMock.set).toHaveBeenCalledTimes(2);
    expect(cookieStoreMock.set).toHaveBeenCalledWith("a", "1", { path: "/" });
    expect(cookieStoreMock.set).toHaveBeenCalledWith("b", "2", { path: "/" });
  });

  it("setAll swallows errors from a read-only RSC cookie store", async () => {
    cookieStoreMock.set.mockImplementation(() => {
      throw new Error("Cookies cannot be modified in a Server Component");
    });
    const { createSupabaseServerClient } = await import("../supabase/server");
    await createSupabaseServerClient();

    expect(() =>
      capturedCookieAdapter!.setAll([
        { name: "x", value: "y", options: {} },
      ])
    ).not.toThrow();
  });
});

describe("getSessionUser", () => {
  it("returns the user object when a session exists", async () => {
    const fakeUser = { id: "user_123", email: "u@example.com" };
    getUserMock.mockResolvedValue({ data: { user: fakeUser }, error: null });

    const { getSessionUser } = await import("../supabase/server");
    const user = await getSessionUser();

    expect(user).toEqual(fakeUser);
    expect(getUserMock).toHaveBeenCalledTimes(1);
  });

  it("returns null when no session is present", async () => {
    getUserMock.mockResolvedValue({ data: { user: null }, error: null });

    const { getSessionUser } = await import("../supabase/server");
    const user = await getSessionUser();

    expect(user).toBeNull();
  });
});
