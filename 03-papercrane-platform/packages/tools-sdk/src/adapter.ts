import { defaultValidate } from './validation';
import type {
  DesignRequest,
  DesignResult,
  PreparedJob,
  RawOutput,
  ToolManifest,
  ValidationError,
} from './types';

/**
 * Base class for every tool wrapped by Paper Crane. Concrete adapters
 * subclass this and implement `prepare/run/parse`. The default `validate()`
 * delegates to the SDK-wide rules; subclasses may override and layer tool-
 * specific checks on top.
 *
 * An `Adapter` is a *local container* tool: `run()` ultimately spawns a
 * Docker/Podman container. For closed-weight HTTPS-backed tools, subclass
 * `RemoteAdapter` instead.
 */
export abstract class Adapter {
  abstract manifest: ToolManifest;

  validate(req: DesignRequest): ValidationError[] {
    return defaultValidate(req);
  }

  /**
   * Stage inputs on disk, materialize any tool-specific config files, and
   * return the spawn-config metadata the runner needs. MUST be pure — no
   * container spawn, no network. The worker layer does the actual exec.
   */
  async prepare(_req: DesignRequest, _workdir: string): Promise<PreparedJob> {
    throw new Error(`Adapter[${this.manifest.id}].prepare() is not implemented`);
  }

  /**
   * Execute the tool and return raw outputs. For local adapters this is a
   * container spawn; see `runInContainer` in `src/run.ts` for the helper.
   */
  async run(_job: PreparedJob): Promise<RawOutput> {
    throw new Error(`Adapter[${this.manifest.id}].run() is not implemented`);
  }

  /**
   * Normalize tool-native outputs into a `DesignResult`.
   */
  async parse(_raw: RawOutput): Promise<DesignResult> {
    throw new Error(`Adapter[${this.manifest.id}].parse() is not implemented`);
  }
}

// ---------- Remote (HTTPS) adapter ----------

export interface HttpRequestConfig {
  url: string;
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  headers?: Record<string, string>;
  body?: unknown;
  timeoutMs?: number;
}

export interface HttpResponse<T = unknown> {
  status: number;
  headers: Record<string, string>;
  data: T;
}

/**
 * Minimal axios-shaped HTTP client. We intentionally avoid pulling axios
 * into the SDK so the package stays zero-runtime-dep; subclasses can swap
 * in the implementation of their choice by extending the default client.
 */
export interface HttpClient {
  request<T = unknown>(config: HttpRequestConfig): Promise<HttpResponse<T>>;
}

export class FetchHttpClient implements HttpClient {
  constructor(private readonly baseHeaders: Record<string, string> = {}) {}

  async request<T = unknown>(config: HttpRequestConfig): Promise<HttpResponse<T>> {
    const controller = new AbortController();
    const timer = config.timeoutMs
      ? setTimeout(() => controller.abort(), config.timeoutMs)
      : undefined;
    try {
      const res = await fetch(config.url, {
        method: config.method ?? 'GET',
        headers: { ...this.baseHeaders, ...(config.headers ?? {}) },
        body: config.body === undefined ? undefined : JSON.stringify(config.body),
        signal: controller.signal,
      });
      const headers: Record<string, string> = {};
      res.headers.forEach((v, k) => {
        headers[k] = v;
      });
      const contentType = res.headers.get('content-type') ?? '';
      const data = contentType.includes('application/json')
        ? ((await res.json()) as T)
        : ((await res.text()) as unknown as T);
      return { status: res.status, headers, data };
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}

export interface RemoteAdapterConfig {
  endpoint: string;
  apiKey?: string;
  extraHeaders?: Record<string, string>;
  httpClient?: HttpClient;
}

/**
 * Base class for closed-weight HTTPS-backed tools (e.g. AlphaFold 3). The
 * contract is identical to `Adapter` — only `run()` differs: it calls an
 * HTTPS endpoint instead of spawning a container.
 *
 * Subclasses access `this.httpClient` to make requests; auth headers are
 * set up in the constructor from `apiKey` + `extraHeaders`.
 */
export abstract class RemoteAdapter extends Adapter {
  public readonly endpoint: string;
  protected readonly httpClient: HttpClient;

  constructor(config: RemoteAdapterConfig) {
    super();
    if (!config.endpoint) {
      throw new Error('RemoteAdapter requires a non-empty endpoint');
    }
    this.endpoint = config.endpoint;
    const headers: Record<string, string> = { 'content-type': 'application/json' };
    if (config.apiKey) {
      headers['authorization'] = `Bearer ${config.apiKey}`;
    }
    Object.assign(headers, config.extraHeaders ?? {});
    this.httpClient = config.httpClient ?? new FetchHttpClient(headers);
  }

  /** Test hook — subclasses generally should use `this.httpClient` directly. */
  getHttpClient(): HttpClient {
    return this.httpClient;
  }
}
