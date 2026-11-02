export type { AppRouter } from "@papercrane/trpc";

const NEXT_DEV_PORTS = new Set(["3000", "3002", "3003"]);
const LOCAL_API = "http://localhost:3001";
const PRODUCTION_API = "https://api.papercrane.bio";

function usableApiUrl(raw: string | undefined): string | undefined {
  if (!raw?.trim()) return undefined;
  try {
    const url = new URL(raw.trim());
    if (url.protocol !== "https:" && url.protocol !== "http:") return undefined;
    const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    // A deployed browser must never send requests to the visitor's localhost.
    if (loopback && (process.env.NODE_ENV === "production" || NEXT_DEV_PORTS.has(url.port))) return undefined;
    return url.toString().replace(/\/$/, "");
  } catch {
    return undefined;
  }
}

/** Public environment aliases must resolve identically in the browser and CSP. */
export function getPublicApiBaseUrl(): string {
  return usableApiUrl(process.env.NEXT_PUBLIC_API_BASE_URL)
    ?? usableApiUrl(process.env.NEXT_PUBLIC_API_URL)
    ?? (process.env.NODE_ENV === "production" ? PRODUCTION_API : LOCAL_API);
}

/** Server-only aliases take precedence; they are never used in browser requests. */
export function getApiBaseUrl(): string {
  if (typeof window === "undefined") {
    const server = usableApiUrl(process.env.API_BASE_URL) ?? usableApiUrl(process.env.API_URL);
    if (server) return server;
  }
  return getPublicApiBaseUrl();
}

export function getTrpcUrl(): string {
  return `${getApiBaseUrl()}/trpc`;
}
