/**
 * Cookie / consent utilities for papercrane.bio.
 *
 * We keep this deliberately tiny: a single localStorage record describing
 * what the user accepted, plus helpers that other code (analytics, embeds)
 * can call before initializing anything that drops a tracker.
 *
 * Categories:
 *   - "essential"  : always allowed; auth, CSRF, session
 *   - "analytics"  : Plausible (cookieless) + any future product analytics
 *   - "preferences": theme, dismissed banners (localStorage only)
 *
 * Storage key uses a `pc_consent` record valid for 1 year. We DO NOT set a
 * networked cookie for consent — `localStorage` is per-device and doesn't
 * leak across domains, which is what we want.
 */

export type ConsentCategory = "essential" | "analytics" | "preferences";

export interface ConsentState {
  /** Schema version so we can re-prompt on material policy changes. */
  v: number;
  /** ISO timestamp of the user's decision. */
  decidedAt: string;
  /** ISO timestamp at which this consent expires and we must re-ask. */
  expiresAt: string;
  /** Per-category decision. `essential` is always true. */
  categories: Record<ConsentCategory, boolean>;
  /** "all" | "essential" | "custom" — useful for analytics on the consent UI itself. */
  choice: "all" | "essential" | "custom";
}

const STORAGE_KEY = "pc_consent";
const CURRENT_SCHEMA_VERSION = 1;
const ONE_YEAR_MS = 365 * 24 * 60 * 60 * 1000;

const isBrowser = (): boolean =>
  typeof window !== "undefined" && typeof window.localStorage !== "undefined";

/**
 * Read the stored consent decision, if any. Returns `null` when:
 *  - we're on the server
 *  - the user has never decided
 *  - the stored record is malformed
 *  - the stored record has expired
 *  - the schema version has been bumped (we re-prompt)
 */
export function getConsent(): ConsentState | null {
  if (!isBrowser()) return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ConsentState;
    if (!parsed || typeof parsed !== "object") return null;
    if (parsed.v !== CURRENT_SCHEMA_VERSION) return null;
    if (parsed.expiresAt && new Date(parsed.expiresAt).getTime() < Date.now())
      return null;
    // Essential is always considered true regardless of stored value.
    parsed.categories = {
      essential: true,
      analytics: !!parsed.categories?.analytics,
      preferences: !!parsed.categories?.preferences,
    };
    return parsed;
  } catch {
    return null;
  }
}

/**
 * Persist a consent decision. `essential` is always forced true.
 */
export function setConsent(
  categories: Partial<Record<ConsentCategory, boolean>>,
  choice: ConsentState["choice"] = "custom",
): ConsentState {
  const now = Date.now();
  const state: ConsentState = {
    v: CURRENT_SCHEMA_VERSION,
    decidedAt: new Date(now).toISOString(),
    expiresAt: new Date(now + ONE_YEAR_MS).toISOString(),
    choice,
    categories: {
      essential: true,
      analytics: !!categories.analytics,
      preferences: !!categories.preferences,
    },
  };
  if (isBrowser()) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
      // Notify any in-page listeners (banner -> analytics init).
      window.dispatchEvent(new CustomEvent("pc:consent-changed", { detail: state }));
    } catch {
      /* localStorage disabled — fail silently and treat as "essential only" */
    }
  }
  return state;
}

export function acceptAll(): ConsentState {
  return setConsent({ analytics: true, preferences: true }, "all");
}

export function acceptEssentialOnly(): ConsentState {
  return setConsent({ analytics: false, preferences: true }, "essential");
}

export function clearConsent(): void {
  if (!isBrowser()) return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
    window.dispatchEvent(new CustomEvent("pc:consent-changed", { detail: null }));
  } catch {
    /* noop */
  }
}

/**
 * True iff the user has actively decided. We use this to know whether to
 * show the banner (no decision yet => show).
 */
export function hasDecided(): boolean {
  return getConsent() !== null;
}

/**
 * Gate for tracker init. Call this *before* loading Plausible, PostHog, etc.
 *   if (canUse("analytics")) initPlausible()
 */
export function canUse(category: ConsentCategory): boolean {
  if (category === "essential") return true;
  // Honor Global Privacy Control as "essential only".
  if (
    isBrowser() &&
    "globalPrivacyControl" in navigator &&
    (navigator as unknown as { globalPrivacyControl?: boolean })
      .globalPrivacyControl === true &&
    category === "analytics"
  ) {
    return false;
  }
  const state = getConsent();
  if (!state) return false;
  return !!state.categories[category];
}

/**
 * Subscribe to consent changes. Returns an unsubscribe function.
 */
export function onConsentChange(
  fn: (state: ConsentState | null) => void,
): () => void {
  if (!isBrowser()) return () => {};
  const handler = (e: Event) => {
    const detail = (e as CustomEvent<ConsentState | null>).detail ?? null;
    fn(detail);
  };
  window.addEventListener("pc:consent-changed", handler);
  return () => window.removeEventListener("pc:consent-changed", handler);
}
