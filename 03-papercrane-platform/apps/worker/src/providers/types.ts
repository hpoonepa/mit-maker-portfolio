/**
 * Provider interface — the contract between the worker and a GPU backend.
 *
 * Plan 03 §2 defines three providers: Modal (managed), Vast.ai (burst),
 * and VPC (frontier). Each implements `spawnJob` which returns an async
 * iterator of per-seed results so the worker can stream them out as
 * design events without buffering.
 */

import type { ToolManifest } from '@papercrane/tools-sdk';

export interface ProviderSeedResult {
  designId: string;
  seed: number;
  metrics: Record<string, number>;
  /** Optional designed amino-acid sequence returned by the model. */
  sequence?: string;
  /** R2 object key where the predicted structure was uploaded by the provider. */
  artifactKey: string;
}

export interface ProviderSpawnResult {
  /** Provider-specific opaque id for the container/task. */
  spawnId: string;
  /** Best-effort estimate for dashboards; may be 0 if unknown. */
  estimatedSeconds: number;
  /** Async iterator of per-seed results, in completion order. */
  seeds: AsyncIterable<ProviderSeedResult>;
  /** Provider-scoped cancel. Called when the worker observes user cancellation. */
  cancel(): Promise<void>;
}

export interface ProviderCostQuote {
  usd: number;
}

export interface ProviderSpawnInputs {
  jobId: string;
  orgId: string;
  toolId: string;
  tier: 'free' | 'pro' | 'frontier';
  /** Normalized DesignRequest from the job row. */
  request: unknown;
  /** Seeds this provider attempt should produce (remaining seeds on resume). */
  numSeeds: number;
  /** Completed upstream stage results for a trusted sequential workflow. */
  previousResults?: ProviderSeedResult[];
  /** Stage position; intermediate stages write checkpoint artifacts separately. */
  workflowStage?: { index: number; total: number };
}

/**
 * The minimal surface the worker needs. Every provider stub must satisfy it.
 * Real Modal/Vast.ai wiring fills the gaps in M2 / plan 03.
 *
 * `cancelJob(spawnId)` is the provider-scoped cancel hook. For Modal this
 * corresponds to the `call_id` returned from `spawn`. We keep the method
 * name `cancelJob` to stay backwards-compatible with the existing
 * jobProcessor; the `spawnId` argument IS the `callId` for Modal.
 */
export interface Provider {
  readonly name: string;
  spawnJob(
    manifest: ToolManifest | undefined,
    inputs: ProviderSpawnInputs,
  ): Promise<ProviderSpawnResult>;
  /** Cancel the running call. `spawnId` is whatever `spawnJob` returned. */
  cancelJob(spawnId: string): Promise<void>;
  getCost(inputs: ProviderSpawnInputs): Promise<ProviderCostQuote>;
}

export interface ProviderRegistry {
  get(name: string): Provider;
  register(provider: Provider): void;
  list(): string[];
}
