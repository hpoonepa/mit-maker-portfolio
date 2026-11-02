/**
 * First-run flag storage for welcome modal + coachmark tooltips.
 *
 * Each flag is versioned (e.g. `pc.seen-welcome=v1`) so that a copy refresh
 * or a UX redesign can reset the flag for all users by bumping the version
 * suffix in the FLAG constants below.
 *
 * SSR-safe: every read is guarded by `typeof window` so these helpers can be
 * imported from server components without crashing the build.
 */

export const FLAG = {
  welcome: "pc.seen-welcome",
  tipNavProjects: "pc.tip-nav-projects",
  tipCmdK: "pc.tip-cmdk",
  tipSubmitJob: "pc.tip-submit-job",
} as const;

export type FlagKey = keyof typeof FLAG;

const VERSION: Record<FlagKey, string> = {
  welcome: "v1",
  tipNavProjects: "v1",
  tipCmdK: "v1",
  tipSubmitJob: "v1",
};

function storageKey(key: FlagKey): string {
  return FLAG[key];
}

/** Returns true if the user has already seen the current version of `key`. */
export function hasSeen(key: FlagKey): boolean {
  if (typeof window === "undefined") return true; // assume seen on server (no flicker)
  try {
    return window.localStorage.getItem(storageKey(key)) === VERSION[key];
  } catch {
    return true; // privacy mode / quota errors → treat as seen, don't nag
  }
}

/** Marks `key` as seen at its current version. No-op on the server. */
export function markSeen(key: FlagKey): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKey(key), VERSION[key]);
  } catch {
    // ignore
  }
}

/** Clears all first-run flags (useful for `?reset-onboarding=1`). */
export function resetAll(): void {
  if (typeof window === "undefined") return;
  try {
    for (const k of Object.keys(FLAG) as FlagKey[]) {
      window.localStorage.removeItem(storageKey(k));
    }
  } catch {
    // ignore
  }
}
