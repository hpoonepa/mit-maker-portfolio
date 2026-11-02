/**
 * RCSB PDB fetch helpers.
 *
 * The Mol* viewer accepts a `structureUrl` and fetches it itself via
 * `plugin.builders.data.download`. For PDB-ID-driven loads we just hand it the
 * canonical RCSB CDN URL: but we ALSO probe RCSB ourselves first so we can:
 *
 *   - Surface 404s (typo'd PDB ID) before mounting the heavy Mol* bundle
 *   - Fall back from `.cif` → `.pdb` for the rare entries where CIF is missing
 *   - Retry transient 5xx with exponential backoff
 *   - Cache successful responses in `sessionStorage` so reopening a target is
 *     instant on the second visit (until the tab is closed)
 *
 * `headFetchPdb` is the entrypoint used by `<StructureLoader>`/`<PdbInput>`.
 */
import { z } from "zod";

/** Local proxy route. The proxy fetches the file from RCSB server-side so we
 *  sidestep CORS preflights and unreliable cross-origin HEADs. The Mol*
 *  viewer is then handed the same `/api/pdb/...` URL to stream from. */
const PDB_PROXY_BASE = "/api/pdb";

/**
 * 4-character PDB IDs: a digit followed by 3 alphanumerics. RCSB also issues
 * 8-character extended IDs (`pdb_00001abc`); we accept both shapes.
 */
const PDB_ID_RE = /^[0-9][A-Za-z0-9]{3}$|^pdb_[0-9a-z]{8}$/;

export const pdbIdSchema = z
  .string()
  .trim()
  .min(4, "PDB IDs are at least 4 characters")
  .max(12, "PDB IDs are at most 12 characters")
  .refine((v) => PDB_ID_RE.test(v), {
    message: "Use a 4-char PDB ID (e.g. 6X1A) or extended ID",
  })
  .transform((v) => v.toUpperCase());

export type PdbFormat = "cif" | "pdb";

export interface PdbUrl {
  id: string;
  format: PdbFormat;
  url: string;
}

/** Build the local proxy URL for a (validated) PDB ID. mmCIF preferred. */
export function pdbCdnUrl(id: string, format: PdbFormat = "cif"): PdbUrl {
  const upper = id.toUpperCase();
  return {
    id: upper,
    format,
    url: `${PDB_PROXY_BASE}/${upper}?format=${format}`,
  };
}

/** Error codes surfaced to the UI. */
export type PdbFetchCode =
  | "invalid_id"
  | "not_found"
  | "network"
  | "rate_limit"
  | "unavailable";

export class PdbFetchError extends Error {
  constructor(
    message: string,
    public readonly code: PdbFetchCode,
    public readonly id?: string,
  ) {
    super(message);
    this.name = "PdbFetchError";
  }
}

/**
 * Validate a user-supplied PDB ID. Throws `PdbFetchError` on bad shape so the
 * caller can render a single error path.
 */
export function validatePdbId(raw: string): string {
  const parsed = pdbIdSchema.safeParse(raw);
  if (!parsed.success) {
    throw new PdbFetchError(
      parsed.error.errors[0]?.message ?? "Invalid PDB ID",
      "invalid_id",
      raw,
    );
  }
  return parsed.data;
}

// ─── Session cache ───────────────────────────────────────────────────────────
//
// Keyed by `pdbId:format`, value = the resolved RCSB URL. This is a probe
// cache: we don't store the structure body itself (Mol* re-downloads it from
// the CDN, which is on its own HTTP cache). Capping the entry count keeps us
// well under the ~5 MB sessionStorage budget even with long IDs.

const CACHE_KEY = "papercrane:pdb-cache:v1";
const CACHE_MAX_ENTRIES = 64; // ~few KB worst-case; nowhere near the 5 MB cap

interface CacheEntry {
  url: string;
  format: PdbFormat;
  ts: number;
}

function cacheRead(): Record<string, CacheEntry> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.sessionStorage.getItem(CACHE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (parsed && typeof parsed === "object") {
      return parsed as Record<string, CacheEntry>;
    }
    return {};
  } catch {
    return {};
  }
}

function cacheWrite(map: Record<string, CacheEntry>): void {
  if (typeof window === "undefined") return;
  try {
    // Trim to most-recent N entries by ts.
    const entries = Object.entries(map).sort(
      ([, a], [, b]) => b.ts - a.ts,
    );
    const trimmed = Object.fromEntries(entries.slice(0, CACHE_MAX_ENTRIES));
    window.sessionStorage.setItem(CACHE_KEY, JSON.stringify(trimmed));
  } catch {
    // Quota / private mode: not fatal.
  }
}

function cacheGet(id: string, format: PdbFormat): CacheEntry | null {
  const map = cacheRead();
  return map[`${id}:${format}`] ?? null;
}

function cacheSet(id: string, format: PdbFormat, url: string): void {
  const map = cacheRead();
  map[`${id}:${format}`] = { url, format, ts: Date.now() };
  cacheWrite(map);
}

/** Test-only: drop the in-tab fetch cache. */
export function _clearPdbCache(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(CACHE_KEY);
  } catch {
    /* ignore */
  }
}

// ─── Fetch with retry + format fallback ──────────────────────────────────────

/** Backoff schedule (ms): three attempts max for transient 5xx. */
const RETRY_DELAYS_MS = [200, 800, 2000] as const;

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const t = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });
}

/**
 * One HEAD attempt, no retry. Returns the response status (or 0 for network
 * errors) and the resolved URL. Kept separate so the retry loop can be
 * tested independently.
 *
 * The proxy answers HEAD via the same handler as GET, so a 200 here means
 * the upstream file exists and the body is fetchable from the same URL.
 */
async function probeHead(
  url: string,
  signal?: AbortSignal,
): Promise<{ status: number; ok: boolean }> {
  try {
    const res = await fetch(url, { method: "HEAD", signal });
    return { status: res.status, ok: res.ok };
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    return { status: 0, ok: false };
  }
}

/**
 * Probe RCSB for a PDB ID. Tries `.cif` first, falls back to `.pdb` on 404,
 * retries 5xx with exponential backoff. Returns the resolved URL on success
 * and throws `PdbFetchError` with a UI-ready message otherwise.
 *
 * `format` lets callers pin a specific format; the default tries CIF→PDB.
 */
export async function headFetchPdb(
  id: string,
  format: PdbFormat | "auto" = "auto",
  signal?: AbortSignal,
): Promise<PdbUrl> {
  const validId = validatePdbId(id);

  // Cache short-circuit: if we resolved this ID earlier in the tab, reuse it.
  if (format === "auto" || format === "cif") {
    const hit = cacheGet(validId, "cif");
    if (hit) return { id: validId, format: "cif", url: hit.url };
  }
  if (format === "auto" || format === "pdb") {
    const hit = cacheGet(validId, "pdb");
    if (hit) return { id: validId, format: "pdb", url: hit.url };
  }

  const tryOrder: PdbFormat[] =
    format === "auto" ? ["cif", "pdb"] : [format];

  let lastNetworkError = false;
  let lastRateLimit = false;
  let lastServerStatus = 0;

  for (const fmt of tryOrder) {
    const target = pdbCdnUrl(validId, fmt);

    // Up to 3 attempts: index 0 has no preceding sleep, then 200/800/2000ms.
    for (let attempt = 0; attempt < RETRY_DELAYS_MS.length; attempt++) {
      if (attempt > 0) {
        await sleep(RETRY_DELAYS_MS[attempt - 1] ?? 0, signal);
      }

      const { status, ok } = await probeHead(target.url, signal);

      if (ok) {
        cacheSet(validId, fmt, target.url);
        return target;
      }

      if (status === 404) {
        // Try the next format (cif → pdb). If we're already on the last
        // format this becomes a hard not_found.
        break;
      }

      if (status === 429) {
        lastRateLimit = true;
        // Retry with backoff: RCSB sometimes throttles bursts of HEADs.
        continue;
      }

      if (status >= 500 && status < 600) {
        lastServerStatus = status;
        // Retry with backoff.
        continue;
      }

      if (status === 0) {
        lastNetworkError = true;
        // Retry: could be a transient DNS / TLS hiccup.
        continue;
      }

      // 4xx other than 404/429: bail without retry, treat as not_found.
      break;
    }
  }

  // Map the worst observed state to a friendly message.
  if (lastRateLimit) {
    throw new PdbFetchError(
      "RCSB rate limit hit: retry in a moment.",
      "rate_limit",
      validId,
    );
  }
  if (lastServerStatus >= 500) {
    throw new PdbFetchError(
      "RCSB unavailable: please try again shortly.",
      "unavailable",
      validId,
    );
  }
  if (lastNetworkError) {
    throw new PdbFetchError(
      "Network error: retry",
      "network",
      validId,
    );
  }
  throw new PdbFetchError(
    `PDB ID "${validId}" not found`,
    "not_found",
    validId,
  );
}
