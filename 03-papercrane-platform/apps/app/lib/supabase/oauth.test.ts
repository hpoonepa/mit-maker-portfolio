import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildCallbackUrl,
  getOAuthProviderAvailability,
} from "./oauth";

const ORIGINAL_ENV = { ...process.env };

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

describe("OAuth provider readiness", () => {
  it("reads enabled providers from Supabase Auth settings", async () => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = "https://example.supabase.co";
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "anon";
    const request = vi.fn(async () =>
      new Response(
        JSON.stringify({ external: { google: true, github: false } }),
        { status: 200 },
      ),
    );

    await expect(getOAuthProviderAvailability(request)).resolves.toEqual({
      google: true,
      github: false,
    });
    expect(request).toHaveBeenCalledWith(
      "https://example.supabase.co/auth/v1/settings",
      { headers: { apikey: "anon" } },
    );
  });

  it("fails closed when Supabase is not configured", async () => {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    await expect(getOAuthProviderAvailability()).resolves.toEqual({
      google: false,
      github: false,
    });
  });
});

describe("OAuth callback URL", () => {
  it("carries the validated invite through OAuth", () => {
    process.env.NEXT_PUBLIC_APP_URL = "https://app.papercrane.bio";
    const url = new URL(buildCallbackUrl("/onboarding", "pc-abcd-efgh"));
    expect(url.origin).toBe("https://app.papercrane.bio");
    expect(url.pathname).toBe("/auth/callback");
    expect(url.searchParams.get("redirectTo")).toBe("/onboarding");
    expect(url.searchParams.get("invite")).toBe("PC-ABCD-EFGH");
  });
});
