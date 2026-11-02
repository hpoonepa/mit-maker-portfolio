import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

/**
 * Tests for `apps/app/lib/supabase/client.ts`.
 *
 * The browser client is a thin wrapper around `@supabase/ssr`'s
 * `createBrowserClient`. We mock that module so no network call is made,
 * and verify:
 *   1. Throws when env is missing.
 *   2. Forwards the URL + anon key to createBrowserClient.
 *   3. Returns the mocked client untouched.
 *   4. Each call returns a fresh client instance (no module-level cache).
 *   5. Exposes auth helpers (signIn / signUp / signOut) on the returned
 *      client surface (smoke test against the mock).
 */

const mockAuth = {
  signInWithPassword: vi.fn(),
  signUp: vi.fn(),
  signOut: vi.fn(),
};

const createBrowserClientMock = vi.fn(() => ({
  auth: mockAuth,
  from: vi.fn(),
}));

vi.mock("@supabase/ssr", () => ({
  createBrowserClient: createBrowserClientMock,
}));

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = "https://test.supabase.co";
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "anon-key";
  createBrowserClientMock.mockClear();
  mockAuth.signInWithPassword.mockReset();
  mockAuth.signUp.mockReset();
  mockAuth.signOut.mockReset();
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  vi.resetModules();
});

describe("createSupabaseBrowserClient", () => {
  it("throws when NEXT_PUBLIC_SUPABASE_URL is missing", async () => {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    const { createSupabaseBrowserClient } = await import(
      "../supabase/client"
    );
    expect(() => createSupabaseBrowserClient()).toThrow(
      /Missing Supabase env/
    );
  });

  it("throws when NEXT_PUBLIC_SUPABASE_ANON_KEY is missing", async () => {
    delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    const { createSupabaseBrowserClient } = await import(
      "../supabase/client"
    );
    expect(() => createSupabaseBrowserClient()).toThrow(
      /Missing Supabase env/
    );
  });

  it("forwards URL and anon key to createBrowserClient", async () => {
    const { createSupabaseBrowserClient } = await import(
      "../supabase/client"
    );
    createSupabaseBrowserClient();

    expect(createBrowserClientMock).toHaveBeenCalledTimes(1);
    expect(createBrowserClientMock).toHaveBeenCalledWith(
      "https://test.supabase.co",
      "anon-key"
    );
  });

  it("returns the client produced by createBrowserClient", async () => {
    const { createSupabaseBrowserClient } = await import(
      "../supabase/client"
    );
    const client = createSupabaseBrowserClient();
    expect(client).toBeDefined();
    expect(client.auth).toBe(mockAuth);
  });

  it("creates a fresh client on every call", async () => {
    const { createSupabaseBrowserClient } = await import(
      "../supabase/client"
    );
    createSupabaseBrowserClient();
    createSupabaseBrowserClient();
    expect(createBrowserClientMock).toHaveBeenCalledTimes(2);
  });

  it("exposes signIn / signUp / signOut auth helpers", async () => {
    mockAuth.signInWithPassword.mockResolvedValue({
      data: { user: { id: "u1" } },
      error: null,
    });
    mockAuth.signUp.mockResolvedValue({
      data: { user: { id: "u1" } },
      error: null,
    });
    mockAuth.signOut.mockResolvedValue({ error: null });

    const { createSupabaseBrowserClient } = await import(
      "../supabase/client"
    );
    const client = createSupabaseBrowserClient();

    await client.auth.signInWithPassword({
      email: "a@b.com",
      password: "pw",
    });
    await client.auth.signUp({ email: "a@b.com", password: "pw" });
    await client.auth.signOut();

    expect(mockAuth.signInWithPassword).toHaveBeenCalledWith({
      email: "a@b.com",
      password: "pw",
    });
    expect(mockAuth.signUp).toHaveBeenCalledTimes(1);
    expect(mockAuth.signOut).toHaveBeenCalledTimes(1);
  });
});
