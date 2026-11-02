import { S3Client, type S3ClientConfig } from "@aws-sdk/client-s3";

/**
 * Configuration for the R2 S3-compatible client.
 *
 * R2 is addressed by account id:
 *   https://{accountId}.r2.cloudflarestorage.com
 * Region is always the literal string "auto" — this is an R2 convention.
 */
export interface R2Config {
  accountId: string;
  accessKeyId: string;
  secretAccessKey: string;
  /** Default bucket name. Callers may still override per-operation. */
  bucket: string;
  /**
   * Optional explicit endpoint override. When unset, derived from
   * accountId. Primarily useful in tests against a local mock.
   */
  endpoint?: string;
}

/**
 * Resolve config from process.env, letting callers override any field.
 * Throws if any required field is missing after the merge.
 */
export function resolveR2Config(overrides?: Partial<R2Config>): R2Config {
  const env: Record<string, string | undefined> =
    typeof process !== "undefined" ? (process.env ?? {}) : {};
  const merged: Partial<R2Config> = {
    accountId: overrides?.accountId ?? env.R2_ACCOUNT_ID,
    accessKeyId: overrides?.accessKeyId ?? env.R2_ACCESS_KEY_ID,
    secretAccessKey: overrides?.secretAccessKey ?? env.R2_SECRET_ACCESS_KEY,
    bucket: overrides?.bucket ?? env.R2_BUCKET,
    endpoint: overrides?.endpoint ?? env.R2_ENDPOINT,
  };

  const missing: string[] = [];
  if (!merged.accountId) missing.push("R2_ACCOUNT_ID");
  if (!merged.accessKeyId) missing.push("R2_ACCESS_KEY_ID");
  if (!merged.secretAccessKey) missing.push("R2_SECRET_ACCESS_KEY");
  if (!merged.bucket) missing.push("R2_BUCKET");

  if (missing.length > 0) {
    throw new Error(
      `storage/client: missing required R2 config: ${missing.join(", ")}`,
    );
  }

  return merged as R2Config;
}

/**
 * Derive the Cloudflare R2 endpoint URL from an account id.
 */
export function r2Endpoint(accountId: string): string {
  return `https://${accountId}.r2.cloudflarestorage.com`;
}

/**
 * Handle returned by `createR2Client`. Keeps the bucket paired with the
 * S3 client so call sites don't have to thread it through every op.
 */
export interface R2Handle {
  readonly client: S3Client;
  readonly bucket: string;
  readonly endpoint: string;
}

/**
 * Factory for an S3 client pointed at Cloudflare R2.
 *
 * Uses the "auto" region convention, virtual-hosted addressing, and
 * the account-scoped endpoint. Callers may pass a fully-populated
 * `R2Config` or rely on env vars.
 */
export function createR2Client(config?: Partial<R2Config>): R2Handle {
  const resolved = resolveR2Config(config);
  const endpoint = resolved.endpoint ?? r2Endpoint(resolved.accountId);

  const clientConfig: S3ClientConfig = {
    region: "auto",
    endpoint,
    credentials: {
      accessKeyId: resolved.accessKeyId,
      secretAccessKey: resolved.secretAccessKey,
    },
    forcePathStyle: false,
  };

  return {
    client: new S3Client(clientConfig),
    bucket: resolved.bucket,
    endpoint,
  };
}
