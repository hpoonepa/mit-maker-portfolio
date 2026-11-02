import { describe, expect, it, vi } from "vitest";
import { ZodError } from "zod";
import {
  buildAcceptUrl,
  sendInviteEmail,
  SendInviteEmailInputSchema,
} from "../../src/services/inviteEmail.js";

/**
 * Unit tests for the invite-email stub. Keeps the contract tight so the
 * follow-up Resend/Postmark implementation is a drop-in replacement:
 *   - Zod validation matches the router's input
 *   - Accept URL builder is deterministic and URI-safe
 *   - The stub logs a fingerprint, never the full token
 */

const VALID = {
  to: "teammate@lab.edu",
  token: "tok_abcdef0123456789abcdef01",
  orgName: "Acme Labs",
  invitedBy: "Alice Example",
  role: "member" as const,
  appBaseUrl: "https://app.papercrane.bio",
};

describe("SendInviteEmailInputSchema", () => {
  it("accepts a well-formed payload", () => {
    expect(() => SendInviteEmailInputSchema.parse(VALID)).not.toThrow();
  });
  it("rejects non-email recipients", () => {
    expect(() =>
      SendInviteEmailInputSchema.parse({ ...VALID, to: "not-an-email" }),
    ).toThrow(ZodError);
  });
  it("rejects short tokens (< 16 chars)", () => {
    expect(() =>
      SendInviteEmailInputSchema.parse({ ...VALID, token: "short" }),
    ).toThrow(ZodError);
  });
  it("rejects unknown roles", () => {
    expect(() =>
      SendInviteEmailInputSchema.parse({ ...VALID, role: "god" }),
    ).toThrow(ZodError);
  });
  it("rejects a non-URL appBaseUrl", () => {
    expect(() =>
      SendInviteEmailInputSchema.parse({ ...VALID, appBaseUrl: "nope" }),
    ).toThrow(ZodError);
  });
});

describe("buildAcceptUrl", () => {
  it("joins base + token with a single slash", () => {
    expect(buildAcceptUrl("https://app.papercrane.bio", "abc")).toBe(
      "https://app.papercrane.bio/invite/abc",
    );
  });
  it("trims trailing slashes on the base URL", () => {
    expect(
      buildAcceptUrl("https://app.papercrane.bio///", "abc"),
    ).toBe("https://app.papercrane.bio/invite/abc");
  });
  it("URI-encodes tokens with special characters", () => {
    // Tokens we mint are URL-safe, but we defensively encode anyway.
    expect(buildAcceptUrl("https://x.io", "a/b c")).toBe(
      "https://x.io/invite/a%2Fb%20c",
    );
  });
});

describe("sendInviteEmail", () => {
  it("logs a structured record with a fingerprint (not the full token)", async () => {
    const info = vi.fn();
    const warn = vi.fn();
    const result = await sendInviteEmail(VALID, {
      logger: { info, warn },
    });

    expect(result.delivered).toBe(true);
    expect(result.acceptUrl).toBe(
      "https://app.papercrane.bio/invite/tok_abcdef0123456789abcdef01",
    );
    expect(result.tokenFingerprint).toBe("tok_abcd");

    expect(info).toHaveBeenCalledTimes(1);
    const [payload, msg] = info.mock.calls[0]!;
    expect(payload).toMatchObject({
      event: "invite.email.stub",
      to: VALID.to,
      orgName: VALID.orgName,
      invitedBy: VALID.invitedBy,
      role: VALID.role,
      acceptUrl: result.acceptUrl,
      tokenFingerprint: "tok_abcd",
    });
    // The fingerprint is a short prefix, not the full token. The accept URL
    // embeds the token by necessity while this is a local-dev stub; once we
    // wire a real provider the URL will be dropped at info level (the
    // service's security note records the rationale).
    expect((payload as { tokenFingerprint: string }).tokenFingerprint).toBe(
      "tok_abcd",
    );
    expect(
      (payload as { tokenFingerprint: string }).tokenFingerprint.length,
    ).toBeLessThan(VALID.token.length);
    expect(msg).toMatch(/invite email/i);
  });

  it("throws ZodError on invalid input (defence in depth vs. the router)", async () => {
    const info = vi.fn();
    const warn = vi.fn();
    await expect(
      sendInviteEmail(
        { ...VALID, to: "not-an-email" } as never,
        { logger: { info, warn } },
      ),
    ).rejects.toThrow(ZodError);
  });
});
