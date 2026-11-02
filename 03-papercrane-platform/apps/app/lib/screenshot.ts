/**
 * Optional viewport-screenshot helper for the feedback widget.
 *
 * `html2canvas` is not in the app's runtime deps (intentionally: it's heavy
 * and we don't want to ship it for everyone). This module dynamically imports
 * it at call time, so it only lands in the bundle if/when the dep is added.
 *
 * If the import fails (typical case during the beta), we resolve to `null`
 * and the widget falls back to "no screenshot, just metadata", so the user
 * still gets a working submission.
 */

export interface ScreenshotResult {
  /** Base64 PNG data URL, or null if capture is unavailable. */
  dataUrl: string | null;
  /** Reason capture was skipped, for diagnostics in the metadata blob. */
  skippedReason?: string;
}

type Html2CanvasFn = (
  el: HTMLElement,
  opts?: Record<string, unknown>,
) => Promise<HTMLCanvasElement>;

interface Html2CanvasModule {
  default: Html2CanvasFn;
}

/**
 * Attempt to capture the current viewport as a PNG data URL. Returns
 * `{ dataUrl: null, skippedReason }` if the dep is unavailable or capture
 * fails: never throws.
 */
export async function captureViewport(): Promise<ScreenshotResult> {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return { dataUrl: null, skippedReason: "no-dom" };
  }

  let mod: Html2CanvasModule;
  try {
    // Dynamic import keeps html2canvas out of the bundle when it's not
    // installed. The empty-catch path is the documented "skip" branch.
    mod = (await import(/* webpackIgnore: true */ "html2canvas").catch(
      () => null,
    )) as Html2CanvasModule | null ?? (null as unknown as Html2CanvasModule);
  } catch {
    return { dataUrl: null, skippedReason: "import-failed" };
  }

  if (!mod || typeof mod.default !== "function") {
    return { dataUrl: null, skippedReason: "html2canvas-not-installed" };
  }

  try {
    const canvas = await mod.default(document.body, {
      backgroundColor: null,
      logging: false,
      useCORS: true,
      width: window.innerWidth,
      height: window.innerHeight,
      x: window.scrollX,
      y: window.scrollY,
      scale: Math.min(window.devicePixelRatio || 1, 2),
    });
    return { dataUrl: canvas.toDataURL("image/png") };
  } catch (err) {
    return {
      dataUrl: null,
      skippedReason: `capture-failed:${(err as Error).message ?? "unknown"}`,
    };
  }
}

// ─── Diagnostics ringbuffer ─────────────────────────────────────────────────
//
// Tiny in-memory caches of the last few console.error calls and the last
// few network failures, captured by the dashboard layout's mount effect.
// These are read by the FeedbackForm to attach reproducer hints to the
// submission's metadata blob. We keep them tiny (<5 entries each) so the
// payload stays under a few KB.

const MAX_CONSOLE_ERRORS = 5;
const MAX_NETWORK_FAILURES = 5;

interface ConsoleErrorEntry {
  ts: string;
  message: string;
}

interface NetworkFailureEntry {
  ts: string;
  url: string;
  status: number;
  method: string;
}

const consoleErrors: ConsoleErrorEntry[] = [];
const networkFailures: NetworkFailureEntry[] = [];

let installed = false;

/**
 * Install global hooks that capture console errors and 4xx/5xx fetch
 * responses into ringbuffers. Idempotent; safe to call multiple times.
 *
 * The hooks are deliberately *additive*: they wrap the existing handlers
 * rather than replacing them, so other dev tools (the tRPC error logger
 * link, Next.js error overlays) keep working.
 */
export function installFeedbackDiagnostics(): void {
  if (installed) return;
  if (typeof window === "undefined") return;
  installed = true;

  const originalError = console.error.bind(console);
  console.error = (...args: unknown[]) => {
    try {
      const message = args
        .map((a) =>
          typeof a === "string"
            ? a
            : a instanceof Error
              ? `${a.name}: ${a.message}`
              : safeStringify(a),
        )
        .join(" ");
      consoleErrors.push({
        ts: new Date().toISOString(),
        message: truncate(message, 500),
      });
      while (consoleErrors.length > MAX_CONSOLE_ERRORS) consoleErrors.shift();
    } catch {
      // Capture must never break console.error.
    }
    originalError(...args);
  };

  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;
    const method = (init?.method ?? "GET").toUpperCase();
    try {
      const res = await originalFetch(input, init);
      if (!res.ok) {
        networkFailures.push({
          ts: new Date().toISOString(),
          url: truncate(url, 256),
          status: res.status,
          method,
        });
        while (networkFailures.length > MAX_NETWORK_FAILURES)
          networkFailures.shift();
      }
      return res;
    } catch (err) {
      networkFailures.push({
        ts: new Date().toISOString(),
        url: truncate(url, 256),
        status: 0,
        method,
      });
      while (networkFailures.length > MAX_NETWORK_FAILURES)
        networkFailures.shift();
      throw err;
    }
  };
}

export function getRecentConsoleErrors(): readonly ConsoleErrorEntry[] {
  return consoleErrors.slice();
}

export function getRecentNetworkFailures(): readonly NetworkFailureEntry[] {
  return networkFailures.slice();
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

function safeStringify(x: unknown): string {
  try {
    return JSON.stringify(x);
  } catch {
    return String(x);
  }
}
