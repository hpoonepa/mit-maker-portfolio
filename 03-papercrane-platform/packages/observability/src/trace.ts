/**
 * Thin wrapper over OpenTelemetry tracing. OTel is an optional peer: if
 * `@opentelemetry/api` is loaded in the host process (because the service
 * configured it), spans are created; otherwise `withSpan` is a pass-through.
 *
 * This keeps `@papercrane/observability` free of a hard OTel dependency while
 * letting services opt in by installing the OTel SDK in their own app.
 */

interface OtelSpan {
  setStatus(status: { code: number; message?: string }): void;
  recordException(error: unknown): void;
  end(): void;
}

interface OtelTracer {
  startActiveSpan<T>(name: string, fn: (span: OtelSpan) => T | Promise<T>): T | Promise<T>;
}

interface OtelApi {
  trace: {
    getTracer(name: string, version?: string): OtelTracer;
  };
  SpanStatusCode: {
    OK: number;
    ERROR: number;
  };
}

let cached: OtelApi | null | undefined;

function loadOtel(): OtelApi | null {
  if (cached !== undefined) return cached;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mod = require('@opentelemetry/api') as OtelApi;
    if (mod && mod.trace && typeof mod.trace.getTracer === 'function') {
      cached = mod;
      return mod;
    }
    cached = null;
    return null;
  } catch {
    cached = null;
    return null;
  }
}

/**
 * Execute `fn` inside a span named `name`. If OpenTelemetry isn't available
 * this simply calls `fn()` with no overhead beyond the module lookup.
 */
export async function withSpan<T>(
  name: string,
  fn: () => Promise<T>,
  tracerName = '@papercrane/observability',
): Promise<T> {
  const otel = loadOtel();
  if (!otel) {
    return fn();
  }

  const tracer = otel.trace.getTracer(tracerName);
  return tracer.startActiveSpan(name, async (span) => {
    try {
      const result = await fn();
      span.setStatus({ code: otel.SpanStatusCode.OK });
      return result;
    } catch (err) {
      span.recordException(err);
      span.setStatus({
        code: otel.SpanStatusCode.ERROR,
        message: err instanceof Error ? err.message : String(err),
      });
      throw err;
    } finally {
      span.end();
    }
  }) as Promise<T>;
}

/** Test/utility hook: reset the cached OTel module lookup. */
export function __resetOtelCache(): void {
  cached = undefined;
}
