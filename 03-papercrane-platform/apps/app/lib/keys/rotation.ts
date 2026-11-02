import type { ApiKeyScope } from "@papercrane/types";

/**
 * Client-side view of an API key row. Fields mirror the `ApiKey` Prisma model
 * plus rotation columns added in migration `20260424130000_apikey_rotation`.
 *
 * The server returns ISO strings (via SuperJSON they're re-hydrated to Date);
 * either shape is acceptable to the helpers below so long as they're coerced
 * before comparison.
 */
export interface KeyRecord {
  id: string;
  name: string;
  prefix: string;
  scopes: ApiKeyScope[];
  createdAt: Date | string;
  lastUsedAt: Date | string | null;
  expiresAt: Date | string | null;
  revokedAt: Date | string | null;
  rotatedAt: Date | string | null;
  graceExpiresAt: Date | string | null;
  rotatedFromId: string | null;
}

export type KeyStatus = "active" | "rotating" | "revoked" | "expired";

const toDate = (v: Date | string | null): Date | null => {
  if (v === null) return null;
  if (v instanceof Date) return v;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
};

/**
 * Derive the display status from the server-authoritative timestamps.
 * Precedence (highest wins): revoked > expired > rotating > active.
 *
 *   active   : usable; no lifecycle timestamps set
 *   rotating : old half of a rotation pair, still inside its 24h grace
 *   expired  : past its TTL, or past its grace window (cron hasn't run yet)
 *   revoked  : `revoked_at` is set, done forever
 */
export function keyStatus(k: KeyRecord, now: Date = new Date()): KeyStatus {
  const revoked = toDate(k.revokedAt);
  if (revoked && revoked <= now) return "revoked";

  const expires = toDate(k.expiresAt);
  if (expires && expires <= now) return "expired";

  const rotatedAt = toDate(k.rotatedAt);
  const graceExpires = toDate(k.graceExpiresAt);
  if (rotatedAt && graceExpires) {
    if (graceExpires <= now) return "expired";
    return "rotating";
  }

  return "active";
}

/**
 * Milliseconds remaining in the grace window, clamped to zero.
 *
 * Always computed from `graceExpiresAt` directly (never `rotatedAt + 24h`)
 * because any drift between the browser clock and the server clock would
 * otherwise produce UI countdowns that diverge from the actual cutoff.
 */
export function graceRemainingMs(k: KeyRecord, now: Date = new Date()): number {
  const graceExpires = toDate(k.graceExpiresAt);
  if (!graceExpires || !toDate(k.rotatedAt)) return 0;
  const delta = graceExpires.getTime() - now.getTime();
  return delta > 0 ? delta : 0;
}

/**
 * Format a remaining-time delta in a compact form. Examples:
 *   5400000  → "1h 30m"
 *   18000000 → "5h"
 *   600000   → "10m"
 *   0        → "expired"
 */
export function formatGraceRemaining(ms: number): string {
  if (ms <= 0) return "expired";
  const totalMinutes = Math.floor(ms / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) return `${minutes}m`;
  if (minutes === 0) return `${hours}h`;
  return `${hours}h ${minutes}m`;
}

/** Callers should only show a Rotate affordance when this returns true. */
export function canRotate(k: KeyRecord, now: Date = new Date()): boolean {
  return keyStatus(k, now) === "active";
}

/** A revoked key cannot be revoked again; everything else can. */
export function canRevoke(k: KeyRecord, now: Date = new Date()): boolean {
  return keyStatus(k, now) !== "revoked";
}

/** 24 hours in ms: grace-window constant, exported for callers that need it. */
export const GRACE_WINDOW_MS = 24 * 60 * 60 * 1000;
