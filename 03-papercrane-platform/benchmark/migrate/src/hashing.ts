/**
 * SHA-256 hashing helpers for benchmark provenance fingerprints.
 *
 * Implements the three fingerprints required by methodology-v1.0.md §4:
 *   1. Input fingerprint      — target PDB + chain + hotspots + target version
 *   2. Config hash            — canonical-JSON of tool config
 *   3. Compute environment    — gpu + driver + cuda + container digest + provider
 *
 * All hashes are 64-char lowercase hex without the `sha256:` prefix to match
 * the Postgres `char(64)` column type used by the loader.
 */

import { createHash } from "node:crypto";
import type { ComputeEnv } from "./schema.js";

/** Compute a SHA-256 hex digest of arbitrary buffer-like input. */
export function sha256Hex(data: string | Buffer | Uint8Array): string {
  const buf =
    typeof data === "string"
      ? Buffer.from(data, "utf8")
      : Buffer.isBuffer(data)
        ? data
        : Buffer.from(data);
  return createHash("sha256").update(buf).digest("hex");
}

/**
 * Canonicalize a JSON value by deep-sorting object keys so two objects with
 * identical content but different key order hash to the same digest.
 */
export function canonicalJson(value: unknown): string {
  return JSON.stringify(sortKeys(value));
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    entries.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return Object.fromEntries(entries.map(([k, v]) => [k, sortKeys(v)]));
  }
  return value;
}

/**
 * Input fingerprint per plan §1:
 *   sha256(pdb_bytes || chain_id || sorted(hotspot_residues) || target_version)
 */
export function inputFingerprint(args: {
  pdbBytes: Buffer | Uint8Array | string;
  chainId: string;
  hotspotResidues: number[];
  targetVersion: number | string;
}): string {
  const { pdbBytes, chainId, hotspotResidues, targetVersion } = args;
  const sortedHotspots = [...hotspotResidues].sort((a, b) => a - b).join(",");
  const pdbBuf =
    typeof pdbBytes === "string"
      ? Buffer.from(pdbBytes, "utf8")
      : Buffer.isBuffer(pdbBytes)
        ? pdbBytes
        : Buffer.from(pdbBytes);
  const suffix = Buffer.from(
    `|${chainId}|${sortedHotspots}|${String(targetVersion)}`,
    "utf8",
  );
  return createHash("sha256")
    .update(pdbBuf)
    .update(suffix)
    .digest("hex");
}

/**
 * Config hash: canonical-JSON of the full tool configuration.
 * Use this to dedupe runs that share identical configs regardless of
 * serialization order.
 */
export function configHash(config: unknown): string {
  return sha256Hex(canonicalJson(config));
}

/**
 * Compute-environment hash: combines the normalized compute-env fields into
 * a single deterministic digest.
 */
export function computeEnvHash(env: ComputeEnv): string {
  const canonical = canonicalJson({
    gpu: env.gpu.trim(),
    driver: env.driver.trim(),
    cuda: env.cuda.trim(),
    container_digest: env.container_digest.replace(/^sha256:/i, "").toLowerCase(),
    provider: env.provider.trim().toLowerCase(),
  });
  return sha256Hex(canonical);
}

/**
 * Results digest: deterministic hash of the ordered design outputs for a run.
 * The re-run verifier uses this to check that a fresh execution reproduces
 * the original results within tolerance (plan §2).
 */
export function resultsDigest(
  designs: Array<{ seed: number; sequence: string; metrics: unknown }>,
): string {
  const sorted = [...designs].sort((a, b) => a.seed - b.seed);
  const canonical = canonicalJson(
    sorted.map((d) => ({
      seed: d.seed,
      sequence: d.sequence,
      metrics: d.metrics,
    })),
  );
  return sha256Hex(canonical);
}

/** Strip the `sha256:` prefix from a hash string if present. */
export function stripPrefix(hash: string): string {
  return hash.replace(/^sha256:/i, "").toLowerCase();
}
