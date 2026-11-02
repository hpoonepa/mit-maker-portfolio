/**
 * R2 key-builder helpers.
 *
 * Layout (per plan 01 §6):
 *   r2://papercrane-prod/
 *     orgs/{org_id}/targets/{target_id}/input.pdb
 *     orgs/{org_id}/jobs/{job_id}/designs/{seed}.cif
 *     orgs/{org_id}/jobs/{job_id}/logs/worker-{attempt}.log
 *
 * All ids are validated to be non-empty and free of path-traversal characters.
 * This is defence-in-depth — callers should already pass trusted ids, but
 * we treat storage keys as a security boundary.
 */

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;

function assertId(name: string, value: unknown): asserts value is string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`storage/paths: ${name} must be a non-empty string`);
  }
  if (!ID_PATTERN.test(value)) {
    throw new Error(
      `storage/paths: ${name} must match ${ID_PATTERN} (got "${value}")`,
    );
  }
}

function assertNonNegativeInt(name: string, value: unknown): asserts value is number {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    !Number.isInteger(value) ||
    value < 0
  ) {
    throw new Error(`storage/paths: ${name} must be a non-negative integer`);
  }
}

/**
 * Key for a target's canonical input PDB.
 *   orgs/{orgId}/targets/{targetId}/input.pdb
 */
export function orgTargetKey(orgId: string, targetId: string): string {
  assertId("orgId", orgId);
  assertId("targetId", targetId);
  return `orgs/${orgId}/targets/${targetId}/input.pdb`;
}

/**
 * Sanitises an uploaded filename — keeps the extension, replaces spaces and
 * non-safe characters with `-`. Caller-provided filenames are NEVER trusted
 * as-is in storage keys (defence against path traversal).
 */
function safeFilename(name: string): string {
  const trimmed = name.trim().slice(-128); // last 128 chars — keeps extension
  const replaced = trimmed.replace(/[^A-Za-z0-9._-]+/g, "-");
  return replaced.replace(/^[-.]+/, "") || "upload.pdb";
}

/**
 * Key for a staging upload that hasn't been promoted to a Target yet.
 *   orgs/{orgId}/uploads/{uploadId}/{safeFilename}
 *
 * `uploadId` is server-minted (caller should not be able to choose it) — the
 * server later moves the bytes to `orgTargetKey` once the row is created.
 */
export function orgUploadStagingKey(
  orgId: string,
  uploadId: string,
  filename: string,
): string {
  assertId("orgId", orgId);
  assertId("uploadId", uploadId);
  if (typeof filename !== "string" || filename.length === 0) {
    throw new Error("storage/paths: filename must be a non-empty string");
  }
  return `orgs/${orgId}/uploads/${uploadId}/${safeFilename(filename)}`;
}

/**
 * Key for a designed structure (one seed) produced by a job.
 *   orgs/{orgId}/jobs/{jobId}/designs/{seed}.cif
 */
export function jobDesignKey(orgId: string, jobId: string, seed: number): string {
  assertId("orgId", orgId);
  assertId("jobId", jobId);
  assertNonNegativeInt("seed", seed);
  return `orgs/${orgId}/jobs/${jobId}/designs/${seed}.cif`;
}

/**
 * Key for a worker log file for a job attempt.
 *   orgs/{orgId}/jobs/{jobId}/logs/worker-{attempt}.log
 */
export function jobLogKey(orgId: string, jobId: string, attempt: number): string {
  assertId("orgId", orgId);
  assertId("jobId", jobId);
  assertNonNegativeInt("attempt", attempt);
  return `orgs/${orgId}/jobs/${jobId}/logs/worker-${attempt}.log`;
}

/**
 * Key for a job's metrics parquet blob.
 *   orgs/{orgId}/jobs/{jobId}/metrics.parquet
 */
export function jobMetricsKey(orgId: string, jobId: string): string {
  assertId("orgId", orgId);
  assertId("jobId", jobId);
  return `orgs/${orgId}/jobs/${jobId}/metrics.parquet`;
}

/**
 * Prefix covering every artifact owned by a job — used by the retention
 * sweeper to delete an entire job's blobs in one pass.
 */
export function jobPrefix(orgId: string, jobId: string): string {
  assertId("orgId", orgId);
  assertId("jobId", jobId);
  return `orgs/${orgId}/jobs/${jobId}/`;
}

/**
 * Prefix covering every artifact owned by an org — used for full-tenant
 * teardown (org deletion, Frontier VPC migration).
 */
export function orgPrefix(orgId: string): string {
  assertId("orgId", orgId);
  return `orgs/${orgId}/`;
}
