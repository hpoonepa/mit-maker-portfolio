/**
 * `parseEnv(schema, env, options)` — the single entrypoint used by every
 * service to validate process.env at startup.
 *
 * Behaviour:
 *   - On success: returns the parsed, typed env. Emits a one-line "warnings"
 *     summary to stderr if any optional vars are missing.
 *   - On failure: prints the standard Paper Crane error block (var names +
 *     descriptions, never values) and either throws (default) or returns
 *     `null` when `checkOnly: true`.
 *
 * Privacy invariant: this function MUST NOT echo any env value, even for
 * well-formed vars, because operators frequently pipe stderr to logs. We only
 * surface var names + description strings (which come from the schema).
 */

import type { ZodIssue, ZodTypeAny } from "zod";
import { z } from "zod";
import {
  ApiEnvSchema,
  AppPublicEnvSchema,
  AppServerEnvSchema,
  WebEnvSchema,
  WorkerEnvSchema,
  productionRequired,
  warnIfMissing,
} from "./schema.js";
import type { ParseEnvOptions, ServiceName } from "./types.js";

const SERVICE_LABEL: Record<ServiceName, string> = {
  api: "Paper Crane API",
  worker: "Paper Crane Worker",
  app: "Paper Crane App",
  web: "Paper Crane Web",
};

/** Result of `parseEnvSafe` — used by tests + the `--check-env` flag. */
export interface ParseEnvResult<T> {
  ok: boolean;
  data: T | null;
  missing: string[];
  malformed: Array<{ name: string; reason: string }>;
  warnings: string[];
}

/**
 * Validate `env` against `schema`. On failure, throws an Error whose `.message`
 * is the rendered error block (so callers can `console.error(err.message)` or
 * just let it bubble up to crash the process).
 */
export function parseEnv<T extends ZodTypeAny>(
  schema: T,
  env: NodeJS.ProcessEnv,
  options: ParseEnvOptions,
): z.infer<T> {
  const result = parseEnvSafe(schema, env, options);
  if (!result.ok || result.data === null) {
    const block = renderError(options.service, result);
    const writeErr = options.err ?? ((line: string) => process.stderr.write(line + "\n"));
    writeErr(block);
    if (options.checkOnly) {
      // In check-only mode we still exit non-zero so CI catches it, but we let
      // the caller decide via the returned `null` instead of throwing.
      return null as unknown as z.infer<T>;
    }
    throw new Error(`invalid environment for ${options.service} service`);
  }

  // Emit non-fatal warnings (e.g. missing optional integrations).
  if (result.warnings.length > 0) {
    const writeOut = options.err ?? ((line: string) => process.stderr.write(line + "\n"));
    writeOut(renderWarnings(options.service, result.warnings));
  }

  return result.data;
}

/**
 * Non-throwing variant. Returns a structured result so the `--check-env` flag
 * can present the outcome and exit cleanly.
 */
export function parseEnvSafe<T extends ZodTypeAny>(
  schema: T,
  env: NodeJS.ProcessEnv,
  options: ParseEnvOptions,
): ParseEnvResult<z.infer<T>> {
  const isTest = env.NODE_ENV === "test";
  const isProd = env.NODE_ENV === "production";

  // 1. Schema parse — catches malformed vars (Stripe key prefix, URL format,
  //    coercion errors). Required-but-missing vars also surface here when the
  //    schema marks them required.
  const parsed = schema.safeParse(env);

  const missing: string[] = [];
  const malformed: Array<{ name: string; reason: string }> = [];
  const warnings: string[] = [];

  if (!parsed.success) {
    for (const issue of parsed.error.issues) {
      classifyIssue(issue, schema, missing, malformed);
    }
  }

  // 2. Production-required overlay — promotes "warn in dev" vars to "fail in
  //    prod" without duplicating schema definitions. We only run this when
  //    schema parsing succeeded OR when the missing var isn't already flagged.
  const reqList = productionRequired[options.service] ?? [];
  if (isProd) {
    for (const name of reqList) {
      const v = env[name];
      if ((!v || v.length === 0) && !missing.includes(name)) {
        missing.push(name);
      }
    }
  }

  // 3. Warn list — vars whose absence isn't fatal but worth flagging.
  const warnList = warnIfMissing[options.service] ?? [];
  for (const name of warnList) {
    const v = env[name];
    if ((!v || v.length === 0) && !missing.includes(name)) {
      warnings.push(name);
    }
  }

  // 4. Test-mode escape hatch: NODE_ENV=test bypasses missing-required errors
  //    so unit tests don't need to set the full env surface. Malformed values
  //    still fail (they indicate a real bug in the test fixture).
  if (isTest && malformed.length === 0 && parsed.success) {
    return { ok: true, data: parsed.data, missing: [], malformed: [], warnings };
  }
  if (isTest && missing.length > 0 && malformed.length === 0) {
    // Build a permissive parse: re-run with the missing vars stubbed out so the
    // schema returns a typed object. We do this only in test mode.
    const stubbed = { ...env };
    for (const name of missing) {
      if (!stubbed[name]) stubbed[name] = stubValueFor(name);
    }
    const retry = schema.safeParse(stubbed);
    if (retry.success) {
      return { ok: true, data: retry.data, missing: [], malformed: [], warnings };
    }
  }

  const fatal = missing.length > 0 || malformed.length > 0;
  if (!fatal && parsed.success) {
    return { ok: true, data: parsed.data, missing, malformed, warnings };
  }

  return {
    ok: false,
    data: null,
    missing,
    malformed,
    warnings,
  };
}

// ---------- helpers ----------

function classifyIssue(
  issue: ZodIssue,
  schema: ZodTypeAny,
  missing: string[],
  malformed: Array<{ name: string; reason: string }>,
): void {
  const name = String(issue.path[0] ?? "<root>");
  if (!name || name === "<root>") return;

  // `invalid_type` with `received: undefined` means the var was simply not set.
  // Anything else (regex mismatch, URL format, coercion failure) is malformed.
  const isMissing =
    issue.code === "invalid_type" &&
    "received" in issue &&
    issue.received === "undefined";

  if (isMissing) {
    if (!missing.includes(name)) missing.push(name);
    return;
  }

  malformed.push({ name, reason: describeIssue(issue, schema, name) });
}

function describeIssue(issue: ZodIssue, schema: ZodTypeAny, name: string): string {
  // Prefer the schema's `.describe()` text when available — it's the same
  // human description we render under "Missing required:".
  const desc = describeField(schema, name);
  const reason = issue.message;
  return desc ? `${reason} (${desc})` : reason;
}

function describeField(schema: ZodTypeAny, name: string): string | undefined {
  const shape = (schema as unknown as { shape?: Record<string, ZodTypeAny> }).shape;
  if (!shape) return undefined;
  const field = shape[name];
  if (!field) return undefined;
  return field.description;
}

function stubValueFor(name: string): string {
  // Test-mode stubs. Chosen to satisfy the most common validators (URL, regex)
  // so test fixtures don't have to know which check is upstream.
  if (name.endsWith("_URL") || name === "DATABASE_URL" || name === "DIRECT_URL") {
    return "http://localhost:0/test";
  }
  if (name === "STRIPE_SECRET_KEY") return "sk_test_stub";
  if (name === "STRIPE_WEBHOOK_SECRET") return "whsec_stub";
  if (name === "NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY") return "pk_test_stub";
  return "test-stub";
}

function renderError<T>(service: ServiceName, result: ParseEnvResult<T>): string {
  const lines: string[] = [];
  lines.push("");
  lines.push(`🚨 ${SERVICE_LABEL[service]} failed to start: invalid environment`);
  lines.push("");

  if (result.missing.length > 0) {
    lines.push("Missing required:");
    for (const name of result.missing) {
      const desc = lookupDescription(service, name);
      lines.push(`  - ${name}${desc ? `: ${desc}` : ""}`);
    }
    lines.push("");
  }

  if (result.malformed.length > 0) {
    lines.push("Malformed:");
    for (const { name, reason } of result.malformed) {
      lines.push(`  - ${name}: ${reason}`);
    }
    lines.push("");
  }

  lines.push("Fix .env.local — see /docs/deploy-env.md for setup walkthrough.");
  lines.push("Exiting.");
  lines.push("");
  return lines.join("\n");
}

function renderWarnings(service: ServiceName, names: string[]): string {
  const lines: string[] = [];
  lines.push("");
  lines.push(`⚠️  ${SERVICE_LABEL[service]}: optional env vars missing`);
  for (const name of names) {
    const desc = lookupDescription(service, name);
    lines.push(`  - ${name}${desc ? `: ${desc}` : ""}`);
  }
  lines.push("(continuing — see /docs/deploy-env.md to enable these features)");
  lines.push("");
  return lines.join("\n");
}

/**
 * Best-effort lookup of a field's `.describe(...)` text.
 */
function lookupDescription(service: ServiceName, name: string): string | undefined {
  const schema =
    service === "api"
      ? ApiEnvSchema
      : service === "worker"
        ? WorkerEnvSchema
        : service === "app"
          ? AppPublicEnvSchema.merge(AppServerEnvSchema)
          : WebEnvSchema;
  const shape = (schema as unknown as { shape?: Record<string, ZodTypeAny> }).shape;
  return shape?.[name]?.description;
}

/**
 * Convenience: run validation and either keep going (parsed env) or, if
 * `argv` includes `--check-env`, print a result line and exit cleanly.
 *
 * Used by the entrypoint of every service so adding the flag is a one-liner.
 */
export function parseEnvOrCheckFlag<T extends ZodTypeAny>(
  schema: T,
  env: NodeJS.ProcessEnv,
  argv: readonly string[],
  options: Omit<ParseEnvOptions, "checkOnly">,
): z.infer<T> {
  const checkOnly = argv.includes("--check-env");
  if (checkOnly) {
    const result = parseEnvSafe(schema, env, { ...options, checkOnly: true });
    const writer = options.out ?? ((line: string) => process.stdout.write(line + "\n"));
    if (result.ok) {
      writer(`✅ ${SERVICE_LABEL[options.service]}: env OK`);
      if (result.warnings.length > 0) {
        writer(renderWarnings(options.service, result.warnings));
      }
      process.exit(0);
    } else {
      const errWriter = options.err ?? ((line: string) => process.stderr.write(line + "\n"));
      errWriter(renderError(options.service, result));
      process.exit(1);
    }
  }
  return parseEnv(schema, env, options);
}
