/**
 * Modal provider — spawns Paper Crane tool Functions on modal.com.
 *
 * Each tool is invoked by name as an already-deployed Modal Function through
 * the official Python SDK. The bridge returns/relays NDJSON events which this
 * class translates into `ProviderSeedResult`s for the worker pipeline.
 *
 * Behavior:
 *   • If MODAL_TOKEN_ID / MODAL_TOKEN_SECRET are absent, fall back to a fake
 *     seed stream so local dev / CI can keep running without Modal auth.
 *   • A hard timeout terminates the SDK bridge and is classified retryable.
 *   • User cancel terminates the bridge and cancels its remote FunctionCall.
 *   • The old injected `ModalClient` path remains only for legacy unit tests;
 *     production never calls its assumed REST endpoints.
 */

import type {
  Provider,
  ProviderCostQuote,
  ProviderSeedResult,
  ProviderSpawnInputs,
  ProviderSpawnResult,
} from "./types";
import type { Logger } from "@papercrane/observability";
import { loadManifest, type ToolManifest } from "@papercrane/tools-sdk";
import {
  jobDesignKey,
  presignGet,
  presignPut,
  type R2Handle,
} from "@papercrane/storage";
import { resolve } from "node:path";
import { ModalClient, type ModalStreamEvent } from "./modalClient";
import { resolveModalFunction } from "./modalFunctionMap";
import {
  findRepoRoot,
  ModalOutputContractError,
  spawnViaModalPool,
} from "../adapters/_modalRunner";

export interface ModalProviderOptions {
  tokenId?: string;
  tokenSecret?: string;
  workspace?: string;
  environment?: string;
  logger: Logger;
  /** Base URL override (primarily for tests). */
  baseUrl?: string;
  /** Inject a ModalClient — used by tests to swap out HTTP. */
  client?: ModalClient;
  /** Fallback stub emission interval (only used when tokens are missing). */
  seedIntervalMs?: number;
  /** Object storage used to stage private inputs and persist Modal outputs. */
  storage?: R2Handle;
  /** Bounded per-job seed fan-out. Env MODAL_SEED_PARALLELISM overrides defaults. */
  seedParallelism?: number;
}

export class ModalTimeoutError extends Error {
  constructor(
    public readonly callId: string,
    public readonly timeoutMs: number,
  ) {
    super(`Modal call ${callId} exceeded ${timeoutMs}ms timeout`);
    this.name = "ModalTimeoutError";
  }
}

/** Default fallback seconds per design when manifest doesn't specify. */
const DEFAULT_SECS_PER_DESIGN = 60;

function resolveSeedParallelism(
  configured: number | undefined,
  manifest: ToolManifest | undefined,
  seedCount: number,
): number {
  const envValue = Number.parseInt(
    process.env.MODAL_SEED_PARALLELISM ?? "",
    10,
  );
  const isCpu =
    manifest?.compute.gpuCount === 0 ||
    manifest?.compute.gpu.toUpperCase() === "CPU";
  const requested =
    configured ?? (Number.isFinite(envValue) ? envValue : isCpu ? 4 : 2);
  return Math.min(
    Math.max(1, seedCount),
    Math.max(1, Math.min(8, Math.floor(requested))),
  );
}

export class ModalProvider implements Provider {
  readonly name = "modal";
  private readonly opts: ModalProviderOptions;
  private readonly client: ModalClient | null;
  private readonly useInjectedClient: boolean;
  private readonly hasCredentials: boolean;

  constructor(opts: ModalProviderOptions) {
    this.opts = opts;
    this.useInjectedClient = Boolean(opts.client);
    this.hasCredentials = Boolean(opts.tokenId && opts.tokenSecret);

    if (opts.client) {
      this.client = opts.client;
    } else {
      this.client = null;
      if (!this.hasCredentials) {
        opts.logger.warn(
          { provider: "modal" },
          "MODAL_TOKEN_* not set; provider will emit fake seed streams only",
        );
      }
    }
  }

  async spawnJob(
    manifest: ToolManifest | undefined,
    inputs: ProviderSpawnInputs,
  ): Promise<ProviderSpawnResult> {
    // The worker's CLI path historically called providers without a manifest,
    // which made every tool inherit the 60-second fallback. That is dangerously
    // short for long-running generators such as BoltzGen (roughly 5-8 minutes per
    // design), so load the same checked-in manifest that resolves the Modal app.
    // Injected-client tests keep requiring an explicit manifest.
    const resolvedManifest =
      manifest ??
      (this.hasCredentials && !this.useInjectedClient
        ? await loadManifest(
            resolve(findRepoRoot(), "tools", inputs.toolId, "manifest.json"),
          )
        : undefined);
    const secsPerDesign =
      resolvedManifest?.compute.estSecondsPerDesign ?? DEFAULT_SECS_PER_DESIGN;
    const serialEstimatedSeconds = secsPerDesign * inputs.numSeeds;

    // No client → stub fallback preserves legacy M1/M2 behavior in dev.
    // In production we MUST fail closed: without real Modal creds the stub
    // fabricates metrics that would land in real Design rows.
    if (!this.hasCredentials && !this.client) {
      if (process.env.NODE_ENV === "production") {
        throw new Error(
          "ModalProvider: refusing to run — no Modal credentials in production; would fabricate metrics",
        );
      }
      return this.spawnStub(inputs, serialEstimatedSeconds);
    }

    if (this.useInjectedClient) {
      if (!manifest) {
        throw new Error("ModalProvider.spawnJob requires a ToolManifest");
      }
      return this.spawnViaClient(manifest, inputs, serialEstimatedSeconds);
    }

    const { logger } = this.opts;
    const fnRef = resolveModalFunction(
      inputs.toolId,
      resolvedManifest?.version,
      this.opts.workspace,
    );

    const seeds = extractSeeds(inputs.request, inputs.numSeeds);
    const parallelism = resolveSeedParallelism(
      this.opts.seedParallelism,
      resolvedManifest,
      seeds.length,
    );
    const estimatedSeconds =
      secsPerDesign * Math.ceil(seeds.length / parallelism);
    const laneTimeoutMs = Math.max(
      secsPerDesign * Math.ceil(seeds.length / parallelism) * 2 * 1000,
      15 * 60 * 1000,
    );
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      MODAL_TOKEN_ID: this.opts.tokenId,
      MODAL_TOKEN_SECRET: this.opts.tokenSecret,
      ...(this.opts.workspace ? { MODAL_WORKSPACE: this.opts.workspace } : {}),
      ...(this.opts.environment
        ? { MODAL_ENVIRONMENT: this.opts.environment }
        : {}),
    };

    logger.info(
      {
        jobId: inputs.jobId,
        fn: fnRef,
        numSeeds: inputs.numSeeds,
        seedParallelism: parallelism,
      },
      "ModalProvider: invoking deployed Modal Function",
    );

    const params = await prepareStorageParams(
      this.opts.storage,
      inputs,
      seeds,
      resolveModalParams(resolvedManifest?.defaultParams, inputs.request),
    );
    const prevOutput = await preparePreviousToolOutput(
      this.opts.storage,
      inputs,
    );

    const run = spawnViaModalPool(
      inputs.toolId,
      {
        jobId: inputs.jobId,
        params,
        seeds,
        ...(prevOutput ? { prevOutput } : {}),
      },
      {
        env,
        workspace: this.opts.workspace,
        environment: this.opts.environment,
        concurrency: parallelism,
        // Model images can have long cold starts. Keep a meaningful floor
        // while still bounding lost/partitioned CLI processes.
        timeoutMs: laneTimeoutMs,
      },
    );

    let cancelled = false;
    const iter: AsyncIterable<ProviderSeedResult> = {
      async *[Symbol.asyncIterator]() {
        for await (const event of run.events) {
          if (cancelled) return;
          if (event.type === "seed") {
            if (!event.artifactKey && !event.structureKey && !event.sequence) {
              const error: Error & { code?: string } = new Error(
                `Modal seed ${event.seed} did not provide a persisted artifact key`,
              );
              error.code = "RUNTIME_ERROR";
              throw error;
            }
            const artifactKey = await ensureOwnedModalArtifact(event, params);
            yield {
              designId: event.designId ?? `${inputs.jobId}-d${event.seed}`,
              seed: event.seed,
              artifactKey,
              metrics: event.metrics ?? {},
              sequence: event.sequence,
            };
          } else if (event.type === "error") {
            const error: Error & { code?: string; retryable?: boolean } =
              new Error(event.message);
            error.code = event.code;
            error.retryable = event.retryable;
            throw error;
          }
        }
      },
    };

    return {
      spawnId: run.spawnId,
      estimatedSeconds,
      seeds: iter,
      cancel: async () => {
        if (cancelled) return;
        cancelled = true;
        await run.cancel();
        logger.info(
          { jobId: inputs.jobId, spawnId: run.spawnId },
          "ModalProvider: CLI run cancelled",
        );
      },
    };
  }

  async cancelJob(spawnId: string): Promise<void> {
    if (this.useInjectedClient && this.client) {
      await this.client.cancelCall(spawnId);
      return;
    }
    // Real CLI calls are cancelled through the per-spawn `cancel` closure,
    // which owns the child process. There is no undocumented REST fallback.
    this.opts.logger.info(
      { spawnId },
      "ModalProvider.cancelJob has no detached CLI handle",
    );
  }

  async getCost(inputs: ProviderSpawnInputs): Promise<ProviderCostQuote> {
    // CLI mode does not expose a provider call ID/cost response, so this is a
    // pre-spawn estimate only. Native cost reconciliation remains future work.
    return { usd: inputs.numSeeds * 0.0004 };
  }

  // ---------- stub fallback (no Modal creds) ----------

  private async spawnViaClient(
    manifest: ToolManifest,
    inputs: ProviderSpawnInputs,
    estimatedSeconds: number,
  ): Promise<ProviderSpawnResult> {
    if (!this.client) {
      if (process.env.NODE_ENV === "production") {
        throw new Error(
          "ModalProvider: refusing to run — no Modal credentials in production; would fabricate metrics",
        );
      }
      return this.spawnStub(inputs, estimatedSeconds);
    }
    const { logger } = this.opts;
    const fnRef = resolveModalFunction(
      manifest.id,
      manifest.version,
      this.opts.workspace,
    );
    const timeoutMs = estimatedSeconds * 2 * 1000;
    const spawn = await this.client.spawnCall({
      fn: fnRef,
      input: {
        job_id: inputs.jobId,
        org_id: inputs.orgId,
        tier: inputs.tier,
        num_seeds: inputs.numSeeds,
        request: resolveModalParams(manifest.defaultParams, inputs.request),
      },
      timeoutSeconds: estimatedSeconds * 2,
    });

    const abort = new AbortController();
    let cancelled = false;
    const timer = setTimeout(() => {
      abort.abort();
      logger.warn(
        { callId: spawn.callId, timeoutMs },
        "ModalProvider: call timed out",
      );
    }, timeoutMs);

    const client = this.client;
    const stream = client.streamCall(spawn.callId, { signal: abort.signal });
    const iter: AsyncIterable<ProviderSeedResult> = {
      async *[Symbol.asyncIterator]() {
        try {
          for await (const evt of stream) {
            if (cancelled) return;
            const seedResult = toSeedResult(evt, inputs);
            if (seedResult) yield seedResult;
            if (evt.type === "error") {
              const err = new Error(evt.message) as Error & {
                code?: string;
                retryable?: boolean;
              };
              err.code = evt.code;
              err.retryable = evt.retryable;
              throw err;
            }
            if (evt.type === "done") return;
          }
        } finally {
          clearTimeout(timer);
        }
      },
    };

    return {
      spawnId: spawn.callId,
      estimatedSeconds,
      seeds: iter,
      cancel: async () => {
        if (cancelled) return;
        cancelled = true;
        clearTimeout(timer);
        abort.abort();
        await client.cancelCall(spawn.callId);
      },
    };
  }

  private spawnStub(
    inputs: ProviderSpawnInputs,
    estimatedSeconds: number,
  ): ProviderSpawnResult {
    const { logger, seedIntervalMs = 2000 } = this.opts;
    const spawnId = `modal-stub-${inputs.jobId}`;
    logger.info(
      { jobId: inputs.jobId, numSeeds: inputs.numSeeds, spawnId },
      "ModalProvider: spawning fake seed stream (no Modal creds)",
    );
    let cancelled = false;
    const requestedSeeds = extractSeeds(inputs.request, inputs.numSeeds);
    const iter: AsyncIterable<ProviderSeedResult> = {
      async *[Symbol.asyncIterator]() {
        for (let i = 0; i < requestedSeeds.length; i++) {
          if (cancelled) return;
          if (i > 0) await new Promise((r) => setTimeout(r, seedIntervalMs));
          if (cancelled) return;
          const seed = requestedSeeds[i]!;
          yield {
            designId: `${inputs.jobId}-d${seed}`,
            seed,
            artifactKey: `orgs/${inputs.orgId}/jobs/${inputs.jobId}/designs/${seed}.cif`,
            // `provenance: 'stub'` self-identifies fabricated dev rows. It's a
            // string, but ProviderSeedResult.metrics is typed Record<string,
            // number> (in ./types, not owned here), so we cast locally rather
            // than widen the shared contract. See handoff note.
            metrics: {
              ipsae: 0.5 + Math.random() * 0.4,
              iptm: 0.4 + Math.random() * 0.5,
              plddt: 70 + Math.random() * 25,
              provenance: "stub",
            } as unknown as Record<string, number>,
          };
        }
      },
    };
    return {
      spawnId,
      estimatedSeconds,
      seeds: iter,
      async cancel() {
        cancelled = true;
      },
    };
  }
}

type ModalArtifactUpload = {
  url: string;
  key: string;
  contentType?: string;
};

/**
 * Keep every persisted design on the worker-reserved organization key. Older
 * sequence-only wrappers emitted Modal-volume paths; when they include the
 * sequence, materialize a valid sequence mmCIF at the presigned R2 target.
 * Structure-producing wrappers must upload their real output themselves.
 */
export async function ensureOwnedModalArtifact(
  event: {
    type: "seed";
    seed: number;
    sequence?: string;
    artifactKey?: string;
    structureKey?: string;
  },
  params: Record<string, unknown>,
  fetchImpl: typeof fetch = fetch,
): Promise<string> {
  const internal =
    params._papercrane && typeof params._papercrane === "object"
      ? (params._papercrane as Record<string, unknown>)
      : {};
  const uploads =
    internal.artifactUploads &&
    typeof internal.artifactUploads === "object" &&
    !Array.isArray(internal.artifactUploads)
      ? (internal.artifactUploads as Record<string, unknown>)
      : {};
  const rawRecord = uploads[String(event.seed)];
  const record =
    rawRecord && typeof rawRecord === "object"
      ? (rawRecord as Partial<ModalArtifactUpload>)
      : undefined;
  if (!record?.url || !record.key) {
    throw new ModalOutputContractError(
      "modal",
      `seed ${event.seed} has no reserved artifact upload`,
    );
  }

  const emittedKey = event.structureKey ?? event.artifactKey;
  if (emittedKey === record.key) return record.key;
  if (!event.sequence) {
    throw new ModalOutputContractError(
      "modal",
      `seed ${event.seed} emitted unowned artifact key '${emittedKey ?? "missing"}'`,
    );
  }

  let response: Response;
  try {
    response = await fetchImpl(record.url, {
      method: "PUT",
      headers: {
        "Content-Type": record.contentType ?? "chemical/x-cif",
      },
      body: sequenceCif(event.sequence),
    });
  } catch (cause) {
    const error: Error & { code?: string; retryable?: boolean } = new Error(
      "sequence artifact upload could not reach object storage",
      { cause },
    );
    error.code = "INFRA_ERROR";
    error.retryable = true;
    throw error;
  }
  if (!response.ok) {
    const error: Error & { code?: string; retryable?: boolean } = new Error(
      `sequence artifact upload failed with status ${response.status}`,
    );
    error.code = "INFRA_ERROR";
    error.retryable = response.status >= 500 || response.status === 429;
    throw error;
  }
  return record.key;
}

function sequenceCif(sequence: string): string {
  const normalized = sequence.toUpperCase().replace(/[\s:]/g, "");
  if (!normalized || !/^[A-Z]+$/.test(normalized)) {
    throw new ModalOutputContractError(
      "modal",
      "sequence-only artifact contains invalid residues",
    );
  }
  const aminoAcids: Record<string, string> = {
    A: "ALA",
    C: "CYS",
    D: "ASP",
    E: "GLU",
    F: "PHE",
    G: "GLY",
    H: "HIS",
    I: "ILE",
    K: "LYS",
    L: "LEU",
    M: "MET",
    N: "ASN",
    P: "PRO",
    Q: "GLN",
    R: "ARG",
    S: "SER",
    T: "THR",
    V: "VAL",
    W: "TRP",
    Y: "TYR",
  };
  const rows = [...normalized].map(
    (residue, index) => `1 ${index + 1} ${aminoAcids[residue] ?? "UNK"} n`,
  );
  return [
    "data_papercrane_sequence",
    "_entry.id papercrane_sequence",
    "_entity.id 1",
    "_entity.type polymer",
    "_entity_poly.entity_id 1",
    "_entity_poly.type 'polypeptide(L)'",
    "_entity_poly.pdbx_seq_one_letter_code_can",
    ";",
    normalized,
    ";",
    "loop_",
    "_entity_poly_seq.entity_id",
    "_entity_poly_seq.num",
    "_entity_poly_seq.mon_id",
    "_entity_poly_seq.hetero",
    ...rows,
    "",
  ].join("\n");
}

function toSeedResult(
  evt: ModalStreamEvent,
  inputs: ProviderSpawnInputs,
): ProviderSeedResult | null {
  if (evt.type !== "seed") return null;
  const seed = evt.seed;
  return {
    seed,
    designId: evt.designId ?? `${inputs.jobId}-d${seed}`,
    artifactKey:
      evt.artifactKey ??
      `orgs/${inputs.orgId}/jobs/${inputs.jobId}/designs/${seed}.cif`,
    metrics: evt.metrics ?? {},
    sequence: evt.sequence,
  };
}

/**
 * Resolve the effective parameters sent to a Modal tool. Manifest defaults
 * establish the baseline; legacy `params`, current `toolParams`, and explicit
 * request fields override them in that order. Keep `toolParams` on the object
 * as well because checked-in Python adapters still merge that nested field.
 */
export function resolveModalParams(
  defaultParams: Record<string, unknown> | undefined,
  request: unknown,
): Record<string, unknown> {
  if (!request || typeof request !== "object" || Array.isArray(request)) {
    return { ...(defaultParams ?? {}) };
  }
  const obj = request as Record<string, unknown>;
  const legacyParams =
    obj.params && typeof obj.params === "object" && !Array.isArray(obj.params)
      ? (obj.params as Record<string, unknown>)
      : {};
  const toolParams =
    obj.toolParams &&
    typeof obj.toolParams === "object" &&
    !Array.isArray(obj.toolParams)
      ? (obj.toolParams as Record<string, unknown>)
      : {};
  return {
    ...(defaultParams ?? {}),
    ...legacyParams,
    ...toolParams,
    ...obj,
  };
}

function extractSeeds(request: unknown, numSeeds: number): number[] {
  if (request && typeof request === "object") {
    const seeds = (request as { seeds?: unknown }).seeds;
    if (Array.isArray(seeds)) {
      const nums = seeds.filter((s): s is number => Number.isInteger(s));
      if (nums.length > 0) return nums;
    }
  }
  return Array.from({ length: Math.max(1, numSeeds) }, (_v, i) => i + 1);
}

async function prepareStorageParams(
  storage: R2Handle | undefined,
  inputs: ProviderSpawnInputs,
  seeds: number[],
  params: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  if (!storage) {
    if (process.env.PAPERCRANE_ALLOW_EPHEMERAL_ARTIFACTS === "1") return params;
    const err: Error & { code?: string } = new Error(
      "ModalProvider: R2 credentials are required; refusing to emit nonexistent artifact keys",
    );
    // This is a deterministic deployment/configuration error. Retrying the
    // same job cannot repair it, so keep it out of the infrastructure retry
    // set and surface the actionable message immediately.
    err.code = "RUNTIME_ERROR";
    throw err;
  }

  const artifactUploads: Record<
    string,
    { url: string; key: string; contentType: string }
  > = {};
  await Promise.all(
    seeds.map(async (seed) => {
      const finalKey = jobDesignKey(inputs.orgId, inputs.jobId, seed);
      const stage = inputs.workflowStage;
      const key =
        stage && stage.index < stage.total - 1
          ? finalKey.replace(
              `/jobs/${inputs.jobId}/designs/`,
              `/jobs/${inputs.jobId}/stages/${stage.index}-${inputs.toolId}/`,
            )
          : finalKey;
      const contentType = "chemical/x-cif";
      artifactUploads[String(seed)] = {
        key,
        contentType,
        url: await presignPut(storage, key, contentType, undefined, 60 * 60),
      };
    }),
  );

  const internal =
    params._papercrane && typeof params._papercrane === "object"
      ? (params._papercrane as Record<string, unknown>)
      : {};
  const toolParams =
    params.toolParams && typeof params.toolParams === "object"
      ? (params.toolParams as Record<string, unknown>)
      : {};
  const directTargetPdb = toolParams.targetPdb ?? params.targetPdb;
  const targetArtifactKey =
    internal.targetArtifactKey ??
    (typeof directTargetPdb === "string" && directTargetPdb.startsWith("orgs/")
      ? directTargetPdb
      : undefined);
  let targetStructureUrl: string | undefined;
  if (typeof targetArtifactKey === "string" && targetArtifactKey.length > 0) {
    assertOwnedArtifactKey(targetArtifactKey, inputs.orgId, "target");
    targetStructureUrl = await presignGet(storage, targetArtifactKey, 60 * 60);
  }

  const directPartnerPdb = toolParams.partnerPdb ?? params.partnerPdb;
  const partnerArtifactKey =
    internal.partnerArtifactKey ??
    (typeof directPartnerPdb === "string" &&
    directPartnerPdb.startsWith("orgs/")
      ? directPartnerPdb
      : undefined);
  let partnerStructureUrl: string | undefined;
  if (typeof partnerArtifactKey === "string" && partnerArtifactKey.length > 0) {
    assertOwnedArtifactKey(partnerArtifactKey, inputs.orgId, "partner");
    partnerStructureUrl = await presignGet(
      storage,
      partnerArtifactKey,
      60 * 60,
    );
  }

  const ligandArtifactKey = toolParams.ligand_sdf ?? params.ligand_sdf;
  let ligandStructureUrl: string | undefined;
  if (typeof ligandArtifactKey === "string" && ligandArtifactKey.length > 0) {
    assertOwnedArtifactKey(ligandArtifactKey, inputs.orgId, "ligand");
    ligandStructureUrl = await presignGet(storage, ligandArtifactKey, 60 * 60);
  }

  return {
    ...params,
    _papercrane: {
      ...internal,
      artifactUploads,
      ...(targetStructureUrl ? { targetStructureUrl } : {}),
      ...(partnerStructureUrl ? { partnerStructureUrl } : {}),
      ...(ligandStructureUrl ? { ligandStructureUrl } : {}),
    },
  };
}

async function preparePreviousToolOutput(
  storage: R2Handle | undefined,
  inputs: ProviderSpawnInputs,
): Promise<
  | {
      designs: Array<{
        seed: number;
        sequence?: string;
        structureKey?: string;
        metrics: Record<string, number>;
      }>;
    }
  | undefined
> {
  if (!inputs.previousResults?.length) return undefined;
  if (!storage) {
    const error: Error & { code?: string } = new Error(
      "ModalProvider: object storage is required between workflow stages",
    );
    error.code = "RUNTIME_ERROR";
    throw error;
  }

  const designs = await Promise.all(
    inputs.previousResults.map(async (result) => {
      assertOwnedArtifactKey(result.artifactKey, inputs.orgId, "target");
      return {
        seed: result.seed,
        ...(result.sequence ? { sequence: result.sequence } : {}),
        structureKey: await presignGet(
          storage,
          result.artifactKey,
          60 * 60,
        ),
        metrics: result.metrics,
      };
    }),
  );
  return { designs };
}

export function assertOwnedArtifactKey(
  key: string,
  orgId: string,
  label: "target" | "partner" | "ligand",
): string {
  const ownedPrefix = `orgs/${orgId}/`;
  if (
    !key.startsWith(ownedPrefix) ||
    key.length === ownedPrefix.length ||
    key.includes("..") ||
    key.includes("//")
  ) {
    const error: Error & { code?: string } = new Error(
      `${label} artifact key is outside this organization`,
    );
    error.code = "INVALID_INPUT";
    throw error;
  }
  return key;
}
