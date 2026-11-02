import { loadConfig, resolveApiKey, type PapercraneConfig } from "./config.js";

export interface ApiClientOptions {
  apiUrl?: string;
  apiKey?: string;
}

export interface ApiResult<T> {
  ok: boolean;
  status: number;
  data?: T;
  error?: string;
}

/**
 * Lightweight wrapper around fetch for the Paper Crane tRPC HTTP surface.
 * The CLI talks to the standalone API's tRPC `/trpc/<procedure>` endpoints with
 * Bearer auth — we don't pull in the @trpc client to keep install size small.
 */
export class ApiClient {
  private apiUrl: string;
  private apiKey?: string;

  constructor(opts: ApiClientOptions = {}, cfg: PapercraneConfig = {}) {
    this.apiUrl = (
      opts.apiUrl ??
      cfg.apiUrl ??
      process.env.PAPERCRANE_API_URL ??
      "https://api.papercrane.bio"
    ).replace(/\/$/, "");
    this.apiKey = opts.apiKey ?? resolveApiKey(cfg);
  }

  static async fromEnv(opts: ApiClientOptions = {}): Promise<ApiClient> {
    const cfg = await loadConfig();
    return new ApiClient(opts, cfg);
  }

  hasAuth(): boolean {
    return Boolean(this.apiKey);
  }

  private headers(): Record<string, string> {
    const h: Record<string, string> = {
      "content-type": "application/json",
      "user-agent": "papercrane-cli/0.1.0",
    };
    if (this.apiKey) h["authorization"] = `Bearer ${this.apiKey}`;
    return h;
  }

  /** Call a tRPC query (HTTP GET via input querystring). */
  async query<T = unknown>(
    procedure: string,
    input?: unknown,
  ): Promise<ApiResult<T>> {
    const qs =
      input === undefined
        ? ""
        : `?input=${encodeURIComponent(JSON.stringify({ json: input }))}`;
    const url = `${this.apiUrl}/trpc/${procedure}${qs}`;
    return this.request<T>("GET", url);
  }

  /** Call a tRPC mutation (HTTP POST). */
  async mutate<T = unknown>(
    procedure: string,
    input?: unknown,
  ): Promise<ApiResult<T>> {
    const url = `${this.apiUrl}/trpc/${procedure}`;
    return this.request<T>("POST", url, { json: input });
  }

  /** Stream a server-sent log endpoint, yielding text chunks. */
  async *streamLogs(jobId: string): AsyncGenerator<string, void, void> {
    const url = `${this.apiUrl}/api/jobs/${encodeURIComponent(jobId)}/logs?follow=1`;
    const res = await fetch(url, { headers: this.headers() });
    if (!res.ok || !res.body) {
      throw new Error(`log stream failed (${res.status})`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { value, done } = await reader.read();
      if (done) return;
      yield decoder.decode(value, { stream: true });
    }
  }

  private async request<T>(
    method: "GET" | "POST",
    url: string,
    body?: unknown,
  ): Promise<ApiResult<T>> {
    try {
      const res = await fetch(url, {
        method,
        headers: this.headers(),
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const text = await res.text();
      const parsed = text.length === 0 ? undefined : safeJson(text);
      // tRPC wraps results in { result: { data: ... } } — unwrap if present.
      const wrapped =
        parsed && typeof parsed === "object" && "result" in parsed
          ? (parsed as { result?: { data?: unknown } }).result?.data
          : parsed;
      const data =
        wrapped && typeof wrapped === "object" && "json" in wrapped
          ? ((wrapped as { json?: T }).json as T)
          : (wrapped as T);
      if (!res.ok) {
        const err =
          (parsed as { error?: { json?: { message?: string }; message?: string } } | undefined)
            ?.error?.json?.message ??
          (parsed as { error?: { message?: string } } | undefined)?.error?.message ??
          `HTTP ${res.status}`;
        return { ok: false, status: res.status, error: err };
      }
      return { ok: true, status: res.status, data };
    } catch (err: unknown) {
      return {
        ok: false,
        status: 0,
        error: err instanceof Error ? err.message : String(err),
      };
    }
  }
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export function requireAuth(client: ApiClient): void {
  if (!client.hasAuth()) {
    throw new Error(
      "not logged in — run `papercrane login` or set PAPERCRANE_API_KEY",
    );
  }
}
