/**
 * Live readiness smoke for the small set of tools we are willing to call
 * verified. This follows the production path: worker provider -> deployed
 * Modal function -> presigned R2 upload -> R2 download.
 *
 * It is intentionally opt-in because it allocates real GPUs and costs money.
 */
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { createLogger } from "@papercrane/observability";
import {
  createR2Client,
  deleteObject,
  jobDesignKey,
  streamObject,
} from "@papercrane/storage";

import { ModalProvider } from "../src/providers/modal";

type CoreTool = "proteinmpnn" | "boltz2" | "rfdiffusion";

const TOOL_REQUESTS: Record<CoreTool, Record<string, unknown>> = {
  proteinmpnn: {
    seeds: [42],
    backbones: [{ name: "smoke_ubiquitin", pdbId: "1UBQ" }],
    temperature: 0.1,
    omit_aas: "CX",
    num_seq_per_target: 1,
  },
  boltz2: {
    seeds: [42],
    targetSeq: "MQIFVKTLTGKTITLEVEPSDTIENVKAKI",
    recycling_steps: 1,
    sampling_steps: 10,
    diffusion_samples: 1,
    use_msa_server: false,
  },
  rfdiffusion: {
    seeds: [42],
    targetPdb: "1UBQ",
    targetChain: "A",
    targetRange: "1-76",
    binder_length_range: [20, 20],
    num_designs: 1,
    inference_steps: 5,
    noise_scale: 1,
  },
};

function loadLocalEnv(): void {
  const candidates = [
    resolve(process.cwd(), ".env.local"),
    resolve(process.cwd(), "..", "..", ".env.local"),
  ];
  for (const path of candidates) {
    if (!existsSync(path)) continue;
    for (const rawLine of readFileSync(path, "utf8").split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line || line.startsWith("#")) continue;
      const equals = line.indexOf("=");
      if (equals <= 0) continue;
      const key = line.slice(0, equals).trim();
      let value = line.slice(equals + 1).trim();
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      process.env[key] ??= value;
    }
    return;
  }
}

function selectedTools(): CoreTool[] {
  const requested = process.argv
    .slice(2)
    .flatMap((arg) => arg.replace(/^--tools?=/, "").split(","))
    .filter(Boolean);
  if (requested.length === 0) return ["proteinmpnn", "boltz2", "rfdiffusion"];
  for (const tool of requested) {
    if (!(tool in TOOL_REQUESTS)) {
      throw new Error(
        `unknown core smoke tool '${tool}'; expected proteinmpnn, boltz2, or rfdiffusion`,
      );
    }
  }
  return requested as CoreTool[];
}

async function smokeTool(provider: ModalProvider, toolId: CoreTool): Promise<void> {
  const orgId = `readiness-${randomUUID()}`;
  const jobId = `smoke-${toolId}-${randomUUID()}`;
  const expectedKey = jobDesignKey(orgId, jobId, 42);
  const cleanupKeys = new Set([expectedKey]);
  const started = Date.now();

  process.stdout.write(`${toolId}: invoking live worker -> Modal -> R2 path\n`);
  try {
    const spawned = await provider.spawnJob(undefined, {
      jobId,
      orgId,
      toolId,
      tier: "pro",
      request: TOOL_REQUESTS[toolId],
      numSeeds: 1,
    });
    const results = [];
    for await (const result of spawned.seeds) results.push(result);
    if (results.length !== 1) {
      throw new Error(`expected exactly one seed artifact, received ${results.length}`);
    }

    const result = results[0]!;
    cleanupKeys.add(result.artifactKey);
    if (result.artifactKey !== expectedKey) {
      throw new Error(`provider returned an unexpected artifact key`);
    }
    const stored = await streamObject(createR2Client(), result.artifactKey);
    const bytes = new Uint8Array(await new Response(stored.body).arrayBuffer());
    const head = new TextDecoder().decode(bytes.slice(0, 256));
    if (bytes.byteLength < 100 || !/(?:data_|ATOM|_entry\.id)/.test(head)) {
      throw new Error(`stored artifact is not a recognizable structure/sequence CIF`);
    }
    process.stdout.write(
      `${toolId}: VERIFIED (${bytes.byteLength} bytes, ${Math.round((Date.now() - started) / 1000)}s)\n`,
    );
  } finally {
    const storage = createR2Client();
    await Promise.all([...cleanupKeys].map((key) => deleteObject(storage, key)));
  }
}

async function main(): Promise<void> {
  loadLocalEnv();
  if (!process.env.MODAL_TOKEN_ID || !process.env.MODAL_TOKEN_SECRET) {
    throw new Error("MODAL_TOKEN_ID and MODAL_TOKEN_SECRET are required");
  }

  const provider = new ModalProvider({
    tokenId: process.env.MODAL_TOKEN_ID,
    tokenSecret: process.env.MODAL_TOKEN_SECRET,
    workspace: process.env.MODAL_WORKSPACE,
    environment: process.env.MODAL_ENVIRONMENT,
    logger: createLogger({ service: "core-tool-readiness", level: "info" }),
    storage: createR2Client(),
    seedParallelism: 1,
  });

  for (const toolId of selectedTools()) await smokeTool(provider, toolId);
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`Core tool smoke FAILED: ${message}\n`);
  process.exit(1);
});
