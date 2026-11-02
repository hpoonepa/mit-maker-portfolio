import { describe, it, expect } from "vitest";
import {
  keyStatus,
  graceRemainingMs,
  formatGraceRemaining,
  canRotate,
  canRevoke,
  type KeyRecord,
} from "@/lib/keys/rotation";

/**
 * State machine (derived client-side from server timestamps):
 *
 *   active    →  revokedAt === null && rotatedAt === null && not expired
 *   rotating  →  revokedAt === null && rotatedAt !== null && graceExpiresAt > now
 *                (old half of a rotation pair; still accepted until grace ends)
 *   expired   →  expiresAt !== null && expiresAt <= now
 *   revoked   →  revokedAt !== null
 *
 * Precedence (highest wins): revoked > expired > rotating > active.
 *
 * Business rules tested below:
 *   - a rotating (grace) key cannot be rotated again
 *   - a revoked or expired key cannot be rotated
 *   - revoked keys cannot be revoked a second time
 *   - grace-remaining uses `graceExpiresAt`, never `rotatedAt + 24h`, because
 *     clock drift between `Date.now()` and server time would otherwise cause
 *     the UI countdown to drift from the server-authoritative value
 */

const NOW = new Date("2026-04-24T12:00:00Z");
const plus = (ms: number) => new Date(NOW.getTime() + ms);
const minus = (ms: number) => new Date(NOW.getTime() - ms);

const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;

function mk(partial: Partial<KeyRecord>): KeyRecord {
  return {
    id: "k1",
    name: "ci-runner",
    prefix: "pc_live_",
    scopes: ["jobs:read"],
    createdAt: minus(DAY),
    lastUsedAt: null,
    expiresAt: null,
    revokedAt: null,
    rotatedAt: null,
    graceExpiresAt: null,
    rotatedFromId: null,
    ...partial,
  };
}

describe("keyStatus", () => {
  it("fresh key is active", () => {
    expect(keyStatus(mk({}), NOW)).toBe("active");
  });

  it("revoked beats everything", () => {
    expect(
      keyStatus(
        mk({ revokedAt: minus(HOUR), rotatedAt: minus(HOUR), graceExpiresAt: plus(HOUR) }),
        NOW,
      ),
    ).toBe("revoked");
    expect(keyStatus(mk({ revokedAt: minus(HOUR), expiresAt: minus(DAY) }), NOW)).toBe(
      "revoked",
    );
  });

  it("expiresAt <= now is expired (when not revoked)", () => {
    expect(keyStatus(mk({ expiresAt: NOW }), NOW)).toBe("expired");
    expect(keyStatus(mk({ expiresAt: minus(1) }), NOW)).toBe("expired");
  });

  it("rotated with live grace is rotating", () => {
    expect(
      keyStatus(mk({ rotatedAt: minus(HOUR), graceExpiresAt: plus(HOUR) }), NOW),
    ).toBe("rotating");
  });

  it("rotated with expired grace is effectively expired (cron will revoke soon)", () => {
    // Until the worker catches up, graceExpiresAt < now is surfaced as expired so
    // the UI stops presenting the key as usable.
    expect(
      keyStatus(mk({ rotatedAt: minus(2 * DAY), graceExpiresAt: minus(HOUR) }), NOW),
    ).toBe("expired");
  });

  it("future expiresAt does not affect status", () => {
    expect(keyStatus(mk({ expiresAt: plus(DAY) }), NOW)).toBe("active");
  });
});

describe("graceRemainingMs", () => {
  it("returns 0 when not rotating", () => {
    expect(graceRemainingMs(mk({}), NOW)).toBe(0);
  });

  it("returns the delta between graceExpiresAt and now", () => {
    expect(
      graceRemainingMs(
        mk({ rotatedAt: minus(HOUR), graceExpiresAt: plus(5 * HOUR) }),
        NOW,
      ),
    ).toBe(5 * HOUR);
  });

  it("clamps at 0 for negative deltas", () => {
    expect(
      graceRemainingMs(
        mk({ rotatedAt: minus(2 * DAY), graceExpiresAt: minus(HOUR) }),
        NOW,
      ),
    ).toBe(0);
  });
});

describe("formatGraceRemaining", () => {
  it("formats hours", () => {
    expect(formatGraceRemaining(5 * HOUR)).toMatch(/5\s*h/i);
  });

  it("formats hours + minutes for < 24h", () => {
    expect(formatGraceRemaining(HOUR + 30 * 60 * 1000)).toMatch(/1h\s*30m/i);
  });

  it("formats < 1h as minutes", () => {
    expect(formatGraceRemaining(30 * 60 * 1000)).toBe("30m");
  });

  it("'expired' for zero/negative", () => {
    expect(formatGraceRemaining(0)).toMatch(/expired|0m/i);
    expect(formatGraceRemaining(-1)).toMatch(/expired|0m/i);
  });
});

describe("canRotate", () => {
  it("allows rotation on active keys", () => {
    expect(canRotate(mk({}), NOW)).toBe(true);
  });

  it("blocks rotation on already-rotating keys (no rotate-chain)", () => {
    expect(
      canRotate(mk({ rotatedAt: minus(HOUR), graceExpiresAt: plus(HOUR) }), NOW),
    ).toBe(false);
  });

  it("blocks rotation on revoked keys", () => {
    expect(canRotate(mk({ revokedAt: minus(HOUR) }), NOW)).toBe(false);
  });

  it("blocks rotation on expired keys", () => {
    expect(canRotate(mk({ expiresAt: minus(HOUR) }), NOW)).toBe(false);
  });
});

describe("canRevoke", () => {
  it("allows revoke on active keys", () => {
    expect(canRevoke(mk({}), NOW)).toBe(true);
  });

  it("allows revoke on rotating keys (admin abort of a rotation)", () => {
    expect(
      canRevoke(mk({ rotatedAt: minus(HOUR), graceExpiresAt: plus(HOUR) }), NOW),
    ).toBe(true);
  });

  it("blocks revoke on already-revoked keys", () => {
    expect(canRevoke(mk({ revokedAt: minus(HOUR) }), NOW)).toBe(false);
  });
});
