import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const redirect = vi.fn((url: URL) => ({ kind: "redirect", url }));
vi.mock("next/server", () => ({
  NextResponse: { redirect },
  NextRequest: class {},
}));

const exchangeCodeForSession = vi.fn();
const signOut = vi.fn(async () => ({ error: null }));
vi.mock("@/lib/supabase/server", () => ({
  createSupabaseServerClient: vi.fn(async () => ({
    auth: { exchangeCodeForSession, signOut },
  })),
}));

const claimInvite = vi.fn();
vi.mock("@/lib/trpc/server", () => ({
  createServerTrpc: vi.fn(async () => ({
    beta: { claimInvite: { mutate: claimInvite } },
  })),
}));

function request(path: string) {
  return { nextUrl: new URL(path, "https://app.papercrane.bio") };
}

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  redirect.mockClear();
  exchangeCodeForSession.mockReset();
  claimInvite.mockReset();
  signOut.mockClear();
  process.env.NEXT_PUBLIC_BETA_GATE = "true";
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

describe("auth callback beta admission", () => {
  it("claims password-signup metadata before redirecting", async () => {
    exchangeCodeForSession.mockResolvedValue({
      data: {
        user: { user_metadata: { beta_invite_code: "PC-ABCD-EFGH" } },
      },
      error: null,
    });
    claimInvite.mockResolvedValue({ ok: true, reason: "ok" });
    const { GET } = await import("./route");

    const result = (await GET(
      request("/auth/callback?code=pkce&redirectTo=%2Fonboarding") as never,
    )) as unknown as { url: URL };

    expect(claimInvite).toHaveBeenCalledWith({ code: "PC-ABCD-EFGH" });
    expect(result.url.pathname).toBe("/onboarding");
    expect(signOut).not.toHaveBeenCalled();
  });

  it("claims an invite carried through Google OAuth", async () => {
    exchangeCodeForSession.mockResolvedValue({
      data: { user: { user_metadata: {} } },
      error: null,
    });
    claimInvite.mockResolvedValue({ ok: true, reason: "ok" });
    const { GET } = await import("./route");

    await GET(
      request(
        "/auth/callback?code=pkce&invite=PC-ABCD-EFGH&redirectTo=%2Fdashboard",
      ) as never,
    );

    expect(claimInvite).toHaveBeenCalledWith({ code: "PC-ABCD-EFGH" });
  });

  it("signs out a new user when no valid beta invite is present", async () => {
    exchangeCodeForSession.mockResolvedValue({
      data: { user: { user_metadata: {} } },
      error: null,
    });
    claimInvite.mockResolvedValue({ ok: false, reason: "required" });
    const { GET } = await import("./route");

    const result = (await GET(
      request("/auth/callback?code=pkce") as never,
    )) as unknown as { url: URL };

    expect(claimInvite).toHaveBeenCalledWith({});
    expect(signOut).toHaveBeenCalledOnce();
    expect(result.url.pathname).toBe("/signup");
    expect(result.url.searchParams.get("error")).toMatch(/valid beta invite/i);
  });

  it("does not run admission when the beta gate is off", async () => {
    process.env.NEXT_PUBLIC_BETA_GATE = "false";
    exchangeCodeForSession.mockResolvedValue({
      data: { user: { user_metadata: {} } },
      error: null,
    });
    const { GET } = await import("./route");

    await GET(request("/auth/callback?code=pkce") as never);

    expect(claimInvite).not.toHaveBeenCalled();
  });
});
