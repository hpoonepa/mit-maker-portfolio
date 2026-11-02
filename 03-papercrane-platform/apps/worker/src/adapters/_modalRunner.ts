/**
 * Shared deployed-Modal transport for Papercrane tool adapters.
 *
 * `spawnViaModal` invokes an already-deployed Function, parses its NDJSON stdout
 * into an async event stream, supports cancellation, and applies a hard
 * timeout. `runViaModal` is the compatibility wrapper used by stage adapters;
 * it drains that stream into a `ToolOutput`.
 *
 * Parameters can contain short-lived storage URLs, so command displays are
 * always redacted. The worker image only needs the `modal` Python package on
 * PATH. Tool source is needed for deployment, never on the job hot path.
 */
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

import type { ToolAdapter, ToolInput, ToolOutput } from "@papercrane/jobs";
import {
  resolveModalFunction,
  type ModalFunctionRef,
} from "../providers/modalFunctionMap";

export class ModalAppNotDeployedError extends Error {
  constructor(slug: string, reason?: string) {
    super(
      reason
        ? `Modal app not deployed for ${slug}: ${reason}`
        : `Modal app not deployed for ${slug}`,
    );
    this.name = "ModalAppNotDeployedError";
  }
}

export class ModalRunFailedError extends Error {
  constructor(
    slug: string,
    public readonly exitCode: number | null,
    public readonly stderrTail: string,
  ) {
    super(
      `deployed Modal invocation for ${slug} exited with code=${exitCode}: ${stderrTail.slice(0, 200)}`,
    );
    this.name = "ModalRunFailedError";
  }
}

export class ModalProviderUnavailableError extends Error {
  readonly code = "PROVIDER_UNAVAILABLE";
  readonly retryable = true;

  constructor(
    slug: string,
    public readonly stderrTail: string,
  ) {
    super(`Modal is unavailable for ${slug}: ${stderrTail.slice(0, 200)}`);
    this.name = "ModalProviderUnavailableError";
  }
}

export class ModalCliTimeoutError extends Error {
  readonly code = "NETWORK_TIMEOUT";
  readonly retryable = true;

  constructor(slug: string, timeoutMs: number) {
    super(`deployed Modal invocation for ${slug} exceeded ${timeoutMs}ms`);
    this.name = "ModalCliTimeoutError";
  }
}

export class ModalOutputContractError extends Error {
  readonly code = "INVALID_OUTPUT";
  readonly retryable = false;

  constructor(slug: string, message: string) {
    super(`Invalid Modal output for ${slug}: ${message}`);
    this.name = "ModalOutputContractError";
  }
}

const MODAL_UNAVAILABLE_RE =
  /could not connect to (?:the )?modal server|connection (?:refused|reset)|service unavailable|temporary failure|name resolution|\b503\b/i;

export function modalRunFailure(
  slug: string,
  exitCode: number | null,
  stderrTail: string,
): Error {
  if (MODAL_UNAVAILABLE_RE.test(stderrTail)) {
    return new ModalProviderUnavailableError(slug, stderrTail);
  }
  return new ModalRunFailedError(slug, exitCode, stderrTail);
}

/**
 * NDJSON event shape produced by each `tools/<slug>/modal_app.py`. Mirrors
 * `ModalStreamEvent` in `providers/modalClient.ts` so we can switch transports
 * without changing the parsing layer.
 */
export type ModalRunEvent =
  | { type: "call"; callId: string }
  | {
      type: "seed";
      seed: number;
      designId?: string;
      sequence?: string;
      structureKey?: string;
      artifactKey?: string;
      metrics?: Record<string, number>;
    }
  | { type: "log"; level?: string; message?: string }
  | { type: "done"; summary?: Record<string, unknown> }
  | { type: "error"; code?: string; message: string; retryable?: boolean };

/**
 * Resolved command-line invocation for a tool. Returned by
 * `resolveModalCommand` so the dry-run script and the real spawn path can
 * share the exact same resolution logic.
 */
export interface ResolvedModalCommand {
  /** Python executable that runs the deployed-function bridge. */
  command: string;
  /** Arguments, ready for `child_process.spawn`. */
  args: string[];
  /** The Modal function ref the command resolves to. */
  fn: ModalFunctionRef;
  /** The absolute path to the `modal_app.py` file. */
  modalAppPath: string;
  /** Joined string form, useful for logs/tests. */
  display: string;
  /** JSON payload written to stdin; never exposed in argv or logs. */
  stdin: string;
}

export interface ResolveOptions {
  /** Override the monorepo root (defaults to cwd-relative). */
  repoRoot?: string;
  /** Function entrypoint inside `modal_app.py`. Defaults to `predict`. */
  entrypoint?: string;
  /** Override the bridge executable (used by deterministic tests). */
  modalBin?: string;
  /** If true, skip the on-disk modal_app.py existence check. */
  skipExistsCheck?: boolean;
  /** Modal workspace override for BYOC credentials. */
  workspace?: string;
  /** Modal environment containing the deployed app. */
  environment?: string;
}

const PAPERCRANE_ENTRYPOINTS: Record<string, string> = {
  alphafold3: "papercrane_dispatch",
  boltz1: "papercrane_dispatch",
  boltz2: "papercrane_dispatch",
  chai1: "papercrane_dispatch",
  chroma: "papercrane_dispatch",
  bindcraft: "papercrane_dispatch",
  proteinmpnn: "papercrane_dispatch",
  rfdiffusion: "papercrane_dispatch",
  esm2: "papercrane_dispatch",
  ligandmpnn: "papercrane_dispatch",
  boltzgen: "papercrane_dispatch",
  esmc: "papercrane_dispatch",
  germinal: "papercrane_dispatch",
  rfdiffusionaa: "papercrane_dispatch",
  rfd3: "papercrane_dispatch",
  rf3: "papercrane_dispatch",
  antifold: "papercrane_dispatch",
  thermompnn: "papercrane_dispatch",
  pdbfixer: "papercrane_dispatch",
  esmfold: "papercrane_dispatch",
  disco: "papercrane_dispatch",
  esmif1: "papercrane_dispatch",
  evoef2: "papercrane_dispatch",
  omegafold: "papercrane_dispatch",
  immunebuilder: "papercrane_dispatch",
  "openmm-relax": "papercrane_dispatch",
  foldseek: "papercrane_dispatch",
  p2rank: "papercrane_dispatch",
  freesasa: "papercrane_dispatch",
  "autodock-vina": "papercrane_dispatch",
  plip: "papercrane_dispatch",
  mmseqs2: "papercrane_dispatch",
  hmmer: "papercrane_dispatch",
  mafft: "papercrane_dispatch",
  dssp: "papercrane_dispatch",
  fpocket: "papercrane_dispatch",
  mdanalysis: "papercrane_dispatch",
  pdb2pqr: "papercrane_dispatch",
  propka: "papercrane_dispatch",
  apbs: "papercrane_dispatch",
  smina: "papercrane_dispatch",
  protparam: "papercrane_dispatch",
  parasail: "papercrane_dispatch",
  "cd-hit": "papercrane_dispatch",
  diamond: "papercrane_dispatch",
  hhsuite: "papercrane_dispatch",
  prody: "papercrane_dispatch",
  "pdb-tools": "papercrane_dispatch",
  prodigy: "papercrane_dispatch",
  arpeggio: "papercrane_dispatch",
  dockq: "papercrane_dispatch",
  solublempnn: "predict",
};

/**
 * Resolve a tool slug + ToolInput into the deployed Function invocation we'd
 * spawn. Pure: does NOT touch Modal, does NOT spawn anything. Used by both
 * the real runner and the dry-run smoke test.
 */
export function resolveModalCommand(
  slug: string,
  input: ToolInput,
  opts: ResolveOptions = {},
): ResolvedModalCommand {
  let fn: ModalFunctionRef;
  try {
    // Version is not in ToolInput today; if a future caller threads it through
    // params, prefer that.
    const versionHint =
      typeof (input.params as Record<string, unknown> | undefined)
        ?.toolVersion === "string"
        ? ((input.params as Record<string, unknown>).toolVersion as string)
        : undefined;
    fn = resolveModalFunction(slug, versionHint, opts.workspace);
  } catch (err) {
    throw new ModalAppNotDeployedError(slug, (err as Error).message);
  }

  const repoRoot = opts.repoRoot ?? findRepoRoot();
  const modalAppPath = resolve(repoRoot, "tools", slug, "modal_app.py");
  const invokerPath = resolve(
    repoRoot,
    "apps",
    "worker",
    "scripts",
    "invoke-deployed-modal.py",
  );

  if (!opts.skipExistsCheck && !existsSync(modalAppPath)) {
    throw new ModalAppNotDeployedError(slug, `missing ${modalAppPath}`);
  }
  if (!opts.skipExistsCheck && !existsSync(invokerPath)) {
    throw new ModalAppNotDeployedError(slug, `missing ${invokerPath}`);
  }

  const entrypoint =
    opts.entrypoint ?? PAPERCRANE_ENTRYPOINTS[slug] ?? "predict";
  const command = opts.modalBin ?? process.env.MODAL_PYTHON_BIN ?? "python3";

  // Build the JSON payload. Adapters receive `seeds` as an array; we forward
  // the canonical fields the modal_app.py predict() signatures all accept.
  const payload = {
    job_id: input.jobId,
    seeds: input.seeds,
    params: input.params,
    prev_output: input.prevOutput,
  };

  const args = [
    relativeFromRoot(invokerPath, repoRoot),
    "--app-name",
    fn.appName,
    "--function-name",
    entrypoint,
    "--source-app",
    relativeFromRoot(modalAppPath, repoRoot),
  ];
  if (fn.returnsEvents) args.push("--returns-events");
  if (opts.environment) args.push("--environment", opts.environment);
  // Shell fixtures need to identify the requested seeds. Sensitive params and
  // signed URLs remain stdin-only in every environment.
  if (opts.modalBin) {
    args.push("--job-id", input.jobId, "--seeds", JSON.stringify(input.seeds));
  }

  return {
    command,
    args,
    fn,
    modalAppPath,
    // Params may contain short-lived signed storage URLs. Never place the
    // literal JSON in logs or persisted job metadata.
    display: `${command} ${args.join(" ")} <json:stdin-redacted>`,
    stdin: JSON.stringify(payload),
  };
}

/**
 * Walk up from `process.cwd()` looking for the monorepo root (the directory
 * containing `tools/` and `apps/`). Falls back to cwd if not found — adapters
 * called from the worker container will already have cwd at the repo root.
 */
export function findRepoRoot(): string {
  let dir = process.cwd();
  for (let i = 0; i < 6; i++) {
    if (existsSync(resolve(dir, "tools")) && existsSync(resolve(dir, "apps"))) {
      return dir;
    }
    const parent = resolve(dir, "..");
    if (parent === dir) break;
    dir = parent;
  }
  return process.cwd();
}

function relativeFromRoot(absolute: string, root: string): string {
  if (absolute.startsWith(root + "/")) return absolute.slice(root.length + 1);
  if (absolute === root) return ".";
  return absolute;
}

export interface RunViaModalOptions {
  onProgress?: (p: number) => void;
  env?: NodeJS.ProcessEnv;
  workspace?: string;
  environment?: string;
  modalBin?: string;
  /** Hard wall-clock bound for the local bridge and its remote FunctionCall. */
  timeoutMs?: number;
  /** Grace period before a stuck CLI is force-killed after cancellation. */
  terminationGraceMs?: number;
}

export interface ModalPoolOptions extends RunViaModalOptions {
  /** Maximum Modal Function calls active at once. */
  concurrency: number;
}

export interface ModalRunHandle {
  spawnId: string;
  command: ResolvedModalCommand;
  events: AsyncIterable<ModalRunEvent>;
  cancel(): Promise<void>;
}

class ModalEventQueue implements AsyncIterable<ModalRunEvent> {
  private values: ModalRunEvent[] = [];
  private waiters: Array<{
    resolve: (result: IteratorResult<ModalRunEvent>) => void;
    reject: (reason: unknown) => void;
  }> = [];
  private ended = false;
  private failure: unknown;

  push(value: ModalRunEvent): void {
    if (this.ended) return;
    const waiter = this.waiters.shift();
    if (waiter) waiter.resolve({ value, done: false });
    else this.values.push(value);
  }

  end(discardBuffered = false): void {
    if (this.ended) return;
    if (discardBuffered) this.values = [];
    this.ended = true;
    for (const waiter of this.waiters.splice(0))
      waiter.resolve({ value: undefined, done: true });
  }

  fail(reason: unknown): void {
    if (this.ended) return;
    this.failure = reason;
    this.ended = true;
    for (const waiter of this.waiters.splice(0)) waiter.reject(reason);
  }

  [Symbol.asyncIterator](): AsyncIterator<ModalRunEvent> {
    return {
      next: () => {
        const value = this.values.shift();
        if (value) return Promise.resolve({ value, done: false });
        if (this.failure) return Promise.reject(this.failure);
        if (this.ended)
          return Promise.resolve({ value: undefined, done: true });
        return new Promise<IteratorResult<ModalRunEvent>>((resolve, reject) => {
          this.waiters.push({ resolve, reject });
        });
      },
    };
  }
}

/**
 * Start the Modal SDK bridge immediately and expose its NDJSON as an async stream.
 * The provider uses this so a job can enter `running`, persist each seed, and
 * cancel the CLI while remote compute is still active.
 */
export function spawnViaModal(
  slug: string,
  input: ToolInput,
  opts: RunViaModalOptions = {},
): ModalRunHandle {
  const cmd = resolveModalCommand(slug, input, {
    workspace: opts.workspace,
    environment: opts.environment,
    modalBin: opts.modalBin,
  });

  const queue = new ModalEventQueue();
  let child: ChildProcess;
  try {
    child = spawn(cmd.command, cmd.args, {
      stdio: ["pipe", "pipe", "pipe"],
      cwd: findRepoRoot(),
      env: opts.env ?? process.env,
    });
  } catch (err) {
    throw new ModalAppNotDeployedError(slug, (err as Error).message);
  }

  if (!child.stdout || !child.stderr) {
    child.kill("SIGTERM");
    throw new ModalAppNotDeployedError(
      slug,
      "spawn produced no stdout/stderr streams",
    );
  }
  child.stdin?.end(cmd.stdin);

  let closed = false;
  let resolveClosed: (() => void) | undefined;
  const closePromise = new Promise<void>((resolveClose) => {
    resolveClosed = resolveClose;
  });
  let terminationPromise: Promise<void> | undefined;
  const terminateChild = (): Promise<void> => {
    if (terminationPromise) return terminationPromise;
    terminationPromise = (async () => {
      if (closed) return;
      child.kill("SIGTERM");
      let graceTimer: NodeJS.Timeout | undefined;
      await Promise.race([
        closePromise,
        new Promise<void>((resolveGrace) => {
          graceTimer = setTimeout(
            resolveGrace,
            opts.terminationGraceMs ?? 5_000,
          );
          graceTimer.unref();
        }),
      ]);
      if (graceTimer) clearTimeout(graceTimer);
      if (!closed) child.kill("SIGKILL");
      await closePromise;
    })();
    return terminationPromise;
  };

  let stderrBuf = "";
  let stdoutBuf = "";
  let sawDone = false;
  let cancelled = false;
  let timedOut = false;
  const timer = opts.timeoutMs
    ? setTimeout(() => {
      timedOut = true;
      queue.fail(new ModalCliTimeoutError(slug, opts.timeoutMs!));
      void terminateChild();
      }, opts.timeoutMs)
    : undefined;
  timer?.unref();

  const acceptLine = (raw: string): void => {
    const line = raw.trim();
    if (!line) return;
    const payload = line.startsWith("data:") ? line.slice(5).trim() : line;
    try {
      const event = JSON.parse(payload) as ModalRunEvent;
      if (!event || typeof event !== "object" || typeof event.type !== "string")
        return;
      if (event.type === "done") sawDone = true;
      queue.push(event);
    } catch {
      // Modal banners and container logs are not part of the NDJSON contract.
    }
  };

  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk: string) => {
    stdoutBuf += chunk;
    let newline = stdoutBuf.indexOf("\n");
    while (newline !== -1) {
      acceptLine(stdoutBuf.slice(0, newline));
      stdoutBuf = stdoutBuf.slice(newline + 1);
      newline = stdoutBuf.indexOf("\n");
    }
  });
  child.stderr.on("data", (chunk: string) => {
    stderrBuf += chunk;
    if (stderrBuf.length > 16_384) stderrBuf = stderrBuf.slice(-16_384);
  });
  child.on("error", (err) =>
    queue.fail(new ModalAppNotDeployedError(slug, err.message)),
  );
  child.on("close", (code) => {
    closed = true;
    resolveClosed?.();
    if (timer) clearTimeout(timer);
    acceptLine(stdoutBuf);
    if (timedOut) {
      return;
    } else if (cancelled) {
      queue.end(true);
    } else if (code !== 0) {
      queue.fail(modalRunFailure(slug, code, stderrBuf));
    } else if (!sawDone) {
      queue.fail(
        new ModalRunFailedError(
          slug,
          code,
          "Modal function exited without a done event",
        ),
      );
    } else {
      queue.end();
    }
  });

  return {
    spawnId: `modal-cli-${child.pid ?? input.jobId}`,
    command: cmd,
    events: queue,
    cancel: async () => {
      if (cancelled || closed) return;
      cancelled = true;
      if (timer) clearTimeout(timer);
      await terminateChild();
    },
  };
}

/**
 * Split a multi-seed request across a bounded number of Modal runs. Each lane
 * keeps one container alive for several seeds, avoiding a fresh CLI app and
 * model load for every design while preserving bounded GPU concurrency.
 */
export function spawnViaModalPool(
  slug: string,
  input: ToolInput,
  opts: ModalPoolOptions,
): ModalRunHandle {
  const concurrency = normalizeModalPoolConcurrency(
    opts.concurrency,
    input.seeds.length,
  );
  if (input.seeds.length <= 1) {
    const seed = input.seeds[0];
    return spawnViaModal(
      slug,
      seed === undefined ? input : modalLaneInput(input, seed),
      opts,
    );
  }

  const command = resolveModalCommand(slug, input, {
    workspace: opts.workspace,
    environment: opts.environment,
    modalBin: opts.modalBin,
  });
  const queue = new ModalEventQueue();
  const seedBatches = Array.from({ length: concurrency }, () => [] as number[]);
  input.seeds.forEach((seed, index) => seedBatches[index % concurrency]?.push(seed));
  const active = new Set<ModalRunHandle>();
  let cancelled = false;
  let completed = 0;

  const runLane = async (seeds: number[]): Promise<void> => {
    const handle = spawnViaModal(slug, modalBatchInput(input, seeds), opts);
    const expected = new Set(seeds);
    const seen = new Set<number>();
    active.add(handle);
    try {
      for await (const event of handle.events) {
        if (cancelled) return;
        // Each child emits done; the pool emits one aggregate done below.
        if (event.type === "done") continue;
        if (event.type === "error") {
          const error: Error & { code?: string; retryable?: boolean } =
            new Error(event.message);
          error.code = event.code;
          error.retryable = event.retryable;
          throw error;
        }
        if (event.type === "seed") {
          if (!expected.has(event.seed)) {
            throw new ModalOutputContractError(
              slug,
              `lane [${seeds.join(",")}] emitted unexpected seed ${event.seed}`,
            );
          }
          if (seen.has(event.seed)) {
            throw new ModalOutputContractError(
              slug,
              `lane [${seeds.join(",")}] emitted seed ${event.seed} more than once`,
            );
          }
          seen.add(event.seed);
        }
        queue.push(event);
      }
      // A cancelled child is expected to end without completing every seed.
      if (cancelled) return;
      const missing = seeds.filter((seed) => !seen.has(seed));
      if (missing.length > 0) {
        throw new ModalOutputContractError(
          slug,
          `lane [${seeds.join(",")}] completed without seeds [${missing.join(",")}]`,
        );
      }
      completed += seen.size;
    } finally {
      active.delete(handle);
    }
  };

  void Promise.all(seedBatches.filter((batch) => batch.length > 0).map(runLane))
    .then(() => {
      if (cancelled) return;
      queue.push({
        type: "done",
        summary: { completed, requested: input.seeds.length, concurrency },
      });
      queue.end();
    })
    .catch(async (error: unknown) => {
      // `cancel()` ends the public queue immediately. A child may reject while
      // its signal is in flight; suppress every such post-cancel lane error.
      if (cancelled) {
        queue.end(true);
        return;
      }
      cancelled = true;
      await Promise.allSettled([...active].map((handle) => handle.cancel()));
      queue.fail(error);
    });

  return {
    spawnId: `modal-pool-${input.jobId}`,
    command,
    events: queue,
    cancel: async () => {
      if (cancelled) return;
      cancelled = true;
      await Promise.allSettled([...active].map((handle) => handle.cancel()));
      queue.end(true);
    },
  };
}

/**
 * A provider lane owns exactly one requested seed and therefore exactly one
 * design. Override both count spellings at every nesting level used by legacy
 * adapters so job-wide counts cannot multiply work inside each lane.
 */
export function modalLaneInput(input: ToolInput, seed: number): ToolInput {
  return modalBatchInput(input, [seed]);
}

/** Normalize a lane batch to exactly one design per requested seed. */
export function modalBatchInput(input: ToolInput, seeds: number[]): ToolInput {
  const params = input.params ?? {};
  const oneDesign = (value: unknown): Record<string, unknown> | undefined =>
    value && typeof value === "object" && !Array.isArray(value)
      ? {
          ...(value as Record<string, unknown>),
          numDesigns: 1,
          num_designs: 1,
          num_seq_per_target: 1,
        }
      : undefined;
  const legacyParams = oneDesign(params.params);
  const toolParams = oneDesign(params.toolParams);
  return {
    ...input,
    seeds,
    params: {
      ...params,
      numDesigns: 1,
      num_designs: 1,
      num_seq_per_target: 1,
      ...(legacyParams ? { params: legacyParams } : {}),
      ...(toolParams ? { toolParams } : {}),
    },
  };
}

export function normalizeModalPoolConcurrency(
  requested: number,
  seedCount: number,
): number {
  const finite = Number.isFinite(requested) ? Math.floor(requested) : 1;
  return Math.min(Math.max(1, seedCount), Math.max(1, Math.min(8, finite)));
}

export async function runViaModal(
  slug: string,
  input: ToolInput,
  opts: RunViaModalOptions = {},
): Promise<ToolOutput> {
  const cmd = resolveModalCommand(slug, input, {
    workspace: opts.workspace,
    environment: opts.environment,
    modalBin: opts.modalBin,
  });
  if ((opts.env ?? process.env).PAPERCRANE_MODAL_DRY_RUN === "1") {
    return {
      designs: [],
      meta: { dryRun: true, command: cmd.display, modalFunction: cmd.fn },
    };
  }

  const handle = spawnViaModal(slug, input, opts);
  const designs: ToolOutput["designs"] = [];
  let summary: Record<string, unknown> | undefined;
  try {
    for await (const evt of handle.events) {
      if (evt.type === "seed") {
        designs.push({
          seed: evt.seed,
          sequence: evt.sequence,
          structureKey: evt.structureKey ?? evt.artifactKey,
          metrics: evt.metrics ?? {},
        });
        opts.onProgress?.(
          Math.min(designs.length / Math.max(input.seeds.length, 1), 1),
        );
      } else if (evt.type === "done") {
        summary = evt.summary;
      } else if (evt.type === "error") {
        const error: Error & { code?: string; retryable?: boolean } = new Error(
          evt.message,
        );
        error.code = evt.code;
        error.retryable = evt.retryable;
        throw error;
      }
    }
  } catch (err) {
    await handle.cancel();
    throw err;
  }
  return {
    designs,
    meta: summary
      ? { command: cmd.display, modalFunction: cmd.fn, summary }
      : { command: cmd.display, modalFunction: cmd.fn },
  };
}

/**
 * Convenience re-export so adapters don't need to depend on the full jobs
 * package surface.
 */
export type { ToolAdapter, ToolInput, ToolOutput };
