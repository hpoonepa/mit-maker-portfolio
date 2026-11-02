/**
 * JobSpec — canonical wire shape for a job submission once it leaves the
 * tRPC `jobs.submit` mutation and lands on the worker.
 *
 * Two pipeline shapes are supported:
 *
 *   • Single-tool: `tool: 'rfdiffusion'`. The worker resolves a single Modal
 *     adapter via `apps/worker/src/adapters/registry.ts`.
 *
 *   • Tool chain: `toolChain: ['rfdiffusion', 'proteinmpnn', 'boltz2']`. The
 *     processor walks each stage, piping the previous stage's output into
 *     the next stage's input. Used by the synth processor (dev) and by the
 *     real worker pipeline once the Modal apps are deployed.
 *
 * `JobSpec` is intentionally serialization-friendly (no Date, no functions)
 * so it survives the BullMQ JSON encode/decode round-trip and can be
 * checkpointed to disk for replay/debug.
 */
import { z } from "zod";

/**
 * One stage in a tool-chain pipeline. The `tool` slug must resolve in the
 * adapter registry (`apps/worker/src/adapters/registry.ts`); `params` are
 * stage-local overrides merged on top of the catalog's `defaultParams`.
 */
export const ToolChainStageSchema = z
  .object({
    tool: z.string().min(1),
    /** Optional pinned version (e.g. `1.1.0`). Falls back to catalog default. */
    version: z.string().optional(),
    /** Stage-local parameter overrides. Validated per-tool by the adapter. */
    params: z.record(z.unknown()).default({}),
  })
  .strict();
export type ToolChainStage = z.infer<typeof ToolChainStageSchema>;

/**
 * Full job specification. Either `tool` (single-tool) or `toolChain`
 * (multi-stage pipeline) MUST be set; the API validates this at submit time.
 */
export const JobSpecSchema = z
  .object({
    /** UUID assigned by the API. */
    jobId: z.string().min(1),
    orgId: z.string().min(1),
    /** Single-tool job: tool slug. Mutually exclusive with `toolChain`. */
    tool: z.string().min(1).optional(),
    /** Pipeline pinning of the single-tool version. */
    toolVersion: z.string().optional(),
    /**
     * Multi-stage pipeline. When non-empty the worker uses the chain
     * processor; otherwise it falls back to single-tool dispatch via
     * `tool` + `toolVersion`.
     */
    toolChain: z.array(ToolChainStageSchema).default([]),
    /** Free-form params for single-tool jobs. */
    params: z.record(z.unknown()).default({}),
    /** Number of designs to generate end-to-end. */
    numDesigns: z.number().int().positive(),
    /** Per-design seeds: usually `[1, 2, ..., numDesigns]`. */
    seeds: z.array(z.number().int()).default([]),
    /** Target id this job is bound to (for grouping designs). */
    targetId: z.string().optional(),
  })
  .strict()
  .refine((s) => Boolean(s.tool) || s.toolChain.length > 0, {
    message: "JobSpec requires either `tool` or a non-empty `toolChain`",
  });
export type JobSpec = z.infer<typeof JobSpecSchema>;

/**
 * Adapter input — what `apps/worker/src/adapters/<slug>.ts` receives.
 *
 * Adapters are stage-local: they don't know about the wider job's chain.
 * The processor extracts a `ToolInput` per stage and threads outputs.
 */
export interface ToolInput {
  jobId: string;
  /** Stage-local params (post-defaults merge). */
  params: Record<string, unknown>;
  /** Seeds this adapter is responsible for in this stage. */
  seeds: number[];
  /** Optional upstream-stage output (e.g. backbones from RFdiffusion). */
  prevOutput?: ToolOutput;
}

/**
 * Adapter output — generic enough for any tool. Concrete adapters return a
 * subset (e.g. RFdiffusion fills `backbones`; Boltz2 fills `metrics`).
 */
export interface ToolOutput {
  /** Per-seed records. Order matches input.seeds. */
  designs: Array<{
    seed: number;
    sequence?: string;
    /** Storage key (R2) for the .cif / .pdb artifact. */
    structureKey?: string;
    metrics?: Record<string, number>;
  }>;
  /** Free-form metadata (e.g. modal call ids, log refs). */
  meta?: Record<string, unknown>;
}

/**
 * Adapter signature. All 52 tool adapters in `apps/worker/src/adapters/`
 * conform to this shape so the registry can dispatch by slug.
 */
export type ToolAdapter = (
  input: ToolInput,
  opts: { onProgress?: (p: number) => void },
) => Promise<ToolOutput>;
