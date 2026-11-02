/**
 * Client-side webhook URL validation.
 *
 * Enforces the guardrails we want BEFORE round-tripping to the server:
 *   - https only
 *   - parseable URL
 *   - length <= 2048
 *   - not a loopback / .local / link-local host in production
 *
 * Kept pure and dependency-free so it can be unit tested with plain vitest.
 */

export type WebhookUrlError =
  | "empty"
  | "too_long"
  | "not_https"
  | "unparseable"
  | "forbidden_host";

export type WebhookUrlResult =
  | { ok: true; url: string }
  | { ok: false; error: WebhookUrlError; message: string };

export const MAX_WEBHOOK_URL_LENGTH = 2048;

/** Hosts we refuse to accept in production. Matched case-insensitively. */
const FORBIDDEN_EXACT_HOSTS = new Set([
  "localhost",
  "127.0.0.1",
  "0.0.0.0",
  "::1",
  "[::1]",
]);

/**
 * Returns true for hosts like `foo.local`, `bar.baz.local`, or the bare
 * string `local`. We reject `.local` because it resolves via mDNS on the
 * user's own network and isn't reachable from our delivery workers.
 */
function isDotLocal(host: string): boolean {
  const h = host.toLowerCase();
  return h === "local" || h.endsWith(".local");
}

function isLinkLocalIpv4(host: string): boolean {
  // 169.254.0.0/16
  return /^169\.254\./.test(host);
}

function isPrivateIpv4(host: string): boolean {
  // 10/8, 192.168/16, 172.16/12
  if (/^10\./.test(host)) return true;
  if (/^192\.168\./.test(host)) return true;
  const m = /^172\.(\d{1,3})\./.exec(host);
  if (m) {
    const second = Number(m[1]);
    if (second >= 16 && second <= 31) return true;
  }
  return false;
}

export interface ValidateOptions {
  /** Defaults to `process.env.NODE_ENV === 'production'`. */
  isProduction?: boolean;
}

export function validateWebhookUrl(
  raw: string,
  opts: ValidateOptions = {},
): WebhookUrlResult {
  const isProduction =
    opts.isProduction ??
    (typeof process !== "undefined" && process.env?.NODE_ENV === "production");

  const value = (raw ?? "").trim();

  if (value.length === 0) {
    return { ok: false, error: "empty", message: "URL is required" };
  }
  if (value.length > MAX_WEBHOOK_URL_LENGTH) {
    return {
      ok: false,
      error: "too_long",
      message: `URL exceeds ${MAX_WEBHOOK_URL_LENGTH} characters`,
    };
  }

  if (!/^https:\/\//i.test(value)) {
    return {
      ok: false,
      error: "not_https",
      message: "URL must start with https://",
    };
  }

  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return {
      ok: false,
      error: "unparseable",
      message: "URL is not a valid URL",
    };
  }

  if (parsed.protocol !== "https:") {
    return {
      ok: false,
      error: "not_https",
      message: "URL must use the https:// protocol",
    };
  }

  if (isProduction) {
    const host = parsed.hostname.toLowerCase();

    if (FORBIDDEN_EXACT_HOSTS.has(host)) {
      return {
        ok: false,
        error: "forbidden_host",
        message: `Cannot use ${host} in production`,
      };
    }
    if (isDotLocal(host)) {
      return {
        ok: false,
        error: "forbidden_host",
        message: "Cannot use .local hosts in production",
      };
    }
    if (isLinkLocalIpv4(host)) {
      return {
        ok: false,
        error: "forbidden_host",
        message: "Cannot use link-local (169.254.x.x) addresses in production",
      };
    }
    if (isPrivateIpv4(host)) {
      return {
        ok: false,
        error: "forbidden_host",
        message: "Cannot use private IP addresses in production",
      };
    }
  }

  return { ok: true, url: parsed.toString() };
}
