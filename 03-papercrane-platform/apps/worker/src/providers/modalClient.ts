/**
 * Thin HTTP wrapper around Modal's REST API.
 *
 * Modal does not publish a Node SDK; from a Node worker we interact with the
 * same HTTPS endpoints their `modal` CLI uses. To keep the worker image small
 * we avoid adding `modal` as a runtime dep and instead hit the documented
 * endpoints directly with `fetch`.
 *
 * Assumed endpoint shape (documented in apps/worker/README.md — "Modal HTTP
 * API assumptions"):
 *
 *   POST   /v1/functions/:workspace/:name/spawn          → { call_id }
 *   GET    /v1/calls/:call_id/stream                     → NDJSON stream of
 *                                                          { type, ... } events
 *   POST   /v1/calls/:call_id/cancel                     → 204
 *   GET    /v1/calls/:call_id/cost                       → { usd_cents }
 *
 * Events we expect on the stream (emitted by the Modal Function itself):
 *   { type: 'seed', seed, designId, metrics, artifactKey }
 *   { type: 'log',  level, message }
 *   { type: 'done', summary? }
 *   { type: 'error', code, message, retryable? }
 *
 * Transient HTTP errors (429, 503) are retried with exponential backoff, up
 * to `maxRetries`. 4xx errors (other than 429) are surfaced immediately as
 * `ModalHttpError` so jobProcessor can mark them user-errors.
 */

import type { ModalFunctionRef } from './modalFunctionMap';

export interface ModalClientOptions {
  /** Base URL for Modal REST API. Defaults to https://api.modal.com. */
  baseUrl?: string;
  tokenId: string;
  tokenSecret: string;
  /** Max retries on 429/503. Defaults to 3. */
  maxRetries?: number;
  /** Initial backoff in ms (doubles each retry). Defaults to 250. */
  backoffMs?: number;
  /** Override fetch (primarily for tests). */
  fetchImpl?: typeof fetch;
}

export interface SpawnCallInput {
  fn: ModalFunctionRef;
  /** JSON-serializable input passed to the Modal Function. */
  input: unknown;
  /** Hard upper bound on wall clock in seconds. */
  timeoutSeconds?: number;
  /** Optional AbortSignal to cooperatively bail out of the POST. */
  signal?: AbortSignal;
}

export interface SpawnCallResult {
  callId: string;
}

/**
 * Events parsed off the streaming endpoint. Mirrors the Modal Function contract.
 */
export type ModalStreamEvent =
  | {
      type: 'seed';
      seed: number;
      designId?: string;
      sequence?: string;
      metrics?: Record<string, number>;
      artifactKey?: string;
    }
  | { type: 'log'; level?: string; message?: string }
  | { type: 'done'; summary?: Record<string, unknown> }
  | { type: 'error'; code?: string; message: string; retryable?: boolean };

export interface CostQuote {
  usd: number;
}

export class ModalHttpError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly body?: string,
  ) {
    super(message);
    this.name = 'ModalHttpError';
  }
}

const RETRIABLE_STATUSES = new Set([429, 503]);

/**
 * Low-level HTTP client. The `ModalProvider` wraps this with Provider-shaped
 * ergonomics (async iterator of seed events, cancel token, etc.).
 */
export class ModalClient {
  private readonly baseUrl: string;
  private readonly tokenId: string;
  private readonly tokenSecret: string;
  private readonly maxRetries: number;
  private readonly backoffMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(opts: ModalClientOptions) {
    this.baseUrl = (opts.baseUrl ?? 'https://api.modal.com').replace(/\/$/, '');
    this.tokenId = opts.tokenId;
    this.tokenSecret = opts.tokenSecret;
    this.maxRetries = opts.maxRetries ?? 3;
    this.backoffMs = opts.backoffMs ?? 250;
    this.fetchImpl = opts.fetchImpl ?? fetch;
  }

  private authHeaders(): Record<string, string> {
    // Modal uses its own token-id/token-secret header pair (see modal CLI source).
    return {
      'Modal-Key': this.tokenId,
      'Modal-Secret': this.tokenSecret,
    };
  }

  private async request(
    path: string,
    init: RequestInit & { retriable?: boolean } = {},
  ): Promise<Response> {
    const url = `${this.baseUrl}${path}`;
    const retriable = init.retriable ?? true;

    let attempt = 0;
    let lastError: unknown;
    while (attempt <= this.maxRetries) {
      try {
        const res = await this.fetchImpl(url, {
          ...init,
          headers: {
            'content-type': 'application/json',
            ...this.authHeaders(),
            ...(init.headers ?? {}),
          },
        });

        if (res.ok) return res;

        if (retriable && RETRIABLE_STATUSES.has(res.status) && attempt < this.maxRetries) {
          await delay(this.backoffMs * 2 ** attempt);
          attempt += 1;
          continue;
        }

        // Surface non-retriable or retries-exhausted errors.
        const body = await safeText(res);
        throw new ModalHttpError(res.status, `Modal ${init.method ?? 'GET'} ${path} failed: ${res.status}`, body);
      } catch (err) {
        // Network-level errors (AbortError, TypeError on fetch) bubble up
        // unchanged — retrying a cancelled abort is wrong.
        if (err instanceof ModalHttpError) throw err;
        if (isAbortError(err)) throw err;

        lastError = err;
        if (attempt < this.maxRetries) {
          await delay(this.backoffMs * 2 ** attempt);
          attempt += 1;
          continue;
        }
        throw err;
      }
    }
    // Should be unreachable, but TS wants a terminal expression.
    throw lastError ?? new Error('modal request: retries exhausted');
  }

  async spawnCall(input: SpawnCallInput): Promise<SpawnCallResult> {
    const { fn, input: payload, timeoutSeconds, signal } = input;
    const versionSuffix = fn.version ? `?version=${encodeURIComponent(fn.version)}` : '';
    const path = `/v1/functions/${encodeURIComponent(fn.workspace)}/${encodeURIComponent(fn.name)}/spawn${versionSuffix}`;
    const res = await this.request(path, {
      method: 'POST',
      body: JSON.stringify({ input: payload, timeout_seconds: timeoutSeconds }),
      signal,
    });
    const json = (await res.json()) as { call_id?: string; callId?: string };
    const callId = json.call_id ?? json.callId;
    if (!callId) throw new Error('Modal spawn response missing call_id');
    return { callId };
  }

  /**
   * Stream events off an in-flight call. Yields parsed JSON objects; malformed
   * lines are logged (via onLog) and skipped.
   */
  async *streamCall(
    callId: string,
    options: { signal?: AbortSignal; onRawLine?: (line: string) => void } = {},
  ): AsyncGenerator<ModalStreamEvent, void, void> {
    const res = await this.request(`/v1/calls/${encodeURIComponent(callId)}/stream`, {
      method: 'GET',
      signal: options.signal,
      // The stream endpoint itself shouldn't be retried mid-read; network layer
      // handles reconnect. Individual retries are gated at spawn time.
      retriable: false,
    });
    if (!res.body) {
      throw new Error('Modal stream response has no body');
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Modal uses NDJSON (one JSON object per line). We also tolerate SSE
        // `data: ...` framing for forward-compat with their streaming gateway.
        let nl = buffer.indexOf('\n');
        while (nl !== -1) {
          const rawLine = buffer.slice(0, nl).trim();
          buffer = buffer.slice(nl + 1);
          nl = buffer.indexOf('\n');
          if (!rawLine) continue;
          options.onRawLine?.(rawLine);
          const payload = rawLine.startsWith('data:') ? rawLine.slice(5).trim() : rawLine;
          if (!payload) continue;
          try {
            yield JSON.parse(payload) as ModalStreamEvent;
          } catch {
            // Malformed line — skip silently; onRawLine receives the raw text.
          }
        }
      }

      // Flush any trailing line.
      const tail = buffer.trim();
      if (tail) {
        const payload = tail.startsWith('data:') ? tail.slice(5).trim() : tail;
        try {
          yield JSON.parse(payload) as ModalStreamEvent;
        } catch {
          /* ignore */
        }
      }
    } finally {
      // Best-effort: releasing the reader lets fetch's abort propagate.
      try {
        reader.releaseLock();
      } catch {
        /* ignore */
      }
    }
  }

  async cancelCall(callId: string): Promise<void> {
    await this.request(`/v1/calls/${encodeURIComponent(callId)}/cancel`, {
      method: 'POST',
    });
  }

  async getCost(callId: string): Promise<CostQuote> {
    const res = await this.request(`/v1/calls/${encodeURIComponent(callId)}/cost`, {
      method: 'GET',
    });
    const json = (await res.json()) as { usd_cents?: number; usd?: number };
    if (typeof json.usd === 'number') return { usd: json.usd };
    if (typeof json.usd_cents === 'number') return { usd: json.usd_cents / 100 };
    return { usd: 0 };
  }
}

// ---------- helpers ----------

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function safeText(res: Response): Promise<string> {
  try {
    return await res.text();
  } catch {
    return '';
  }
}

function isAbortError(err: unknown): boolean {
  if (!err || typeof err !== 'object') return false;
  const name = (err as { name?: string }).name;
  return name === 'AbortError';
}
