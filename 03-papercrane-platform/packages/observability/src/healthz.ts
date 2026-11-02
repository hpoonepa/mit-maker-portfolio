export interface HealthCheckResult {
  ok: boolean;
  durationMs: number;
  error?: string;
}

export interface HealthResponse {
  ok: boolean;
  checks: Record<string, HealthCheckResult>;
  timestamp: string;
}

export type HealthCheck = () => Promise<boolean>;

/**
 * Run all checks in parallel and assemble a standard healthz response.
 * `ok` is true only when every check returns `true` without throwing.
 */
export async function buildHealthResponse(
  checks: Record<string, HealthCheck>,
): Promise<HealthResponse> {
  const names = Object.keys(checks);
  const results = await Promise.all(
    names.map(async (name): Promise<[string, HealthCheckResult]> => {
      const start = Date.now();
      try {
        const ok = await checks[name]!();
        return [name, { ok, durationMs: Date.now() - start }];
      } catch (err) {
        return [
          name,
          {
            ok: false,
            durationMs: Date.now() - start,
            error: err instanceof Error ? err.message : String(err),
          },
        ];
      }
    }),
  );

  const checksMap: Record<string, HealthCheckResult> = {};
  let overallOk = true;
  for (const [name, result] of results) {
    checksMap[name] = result;
    if (!result.ok) overallOk = false;
  }

  return {
    ok: overallOk,
    checks: checksMap,
    timestamp: new Date().toISOString(),
  };
}
