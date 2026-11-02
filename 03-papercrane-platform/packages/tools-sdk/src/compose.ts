import { Adapter } from './adapter';
import type {
  DesignRequest,
  DesignResult,
  PreparedJob,
  PreparedStage,
  RawOutput,
  ToolManifest,
  ValidationError,
} from './types';

interface ComposedRawOutput extends RawOutput {
  stageOutputs: Array<{ toolId: string; raw: RawOutput; parsed: DesignResult }>;
}

/**
 * Compose two adapters A → B into a single adapter: A runs first, then B
 * consumes A's designs as its inputs. The canonical use case is
 * RFdiffusion (backbone) → ProteinMPNN (sequence).
 *
 * The composed adapter:
 *   - Validates the request against the *first* adapter only (downstream
 *     tools inherit the shape). Tool-specific downstream constraints are
 *     the first adapter's responsibility to flag.
 *   - `prepare()` prepares both stages against subdirs of `workdir`
 *     (`workdir/stage-0`, `workdir/stage-1`) so sync'd output paths stay
 *     deterministic.
 *   - `run()` executes A, then passes A's designs as the structural inputs
 *     to B and runs B.
 *   - `parse()` returns B's normalized result, but decorates
 *     `runMetadata.stages` with the ordered tool ids.
 */
export function compose(first: Adapter, second: Adapter): Adapter {
  const composedManifest: ToolManifest = {
    id: `${first.manifest.id}+${second.manifest.id}`,
    displayName: `${first.manifest.displayName} → ${second.manifest.displayName}`,
    version: `${first.manifest.version}+${second.manifest.version}`,
    adapterVersion: `${first.manifest.adapterVersion}+${second.manifest.adapterVersion}`,
    category: 'composite',
    tier: pickStricterTier(first.manifest.tier, second.manifest.tier),
    license: `${first.manifest.license}; ${second.manifest.license}`,
    image: `${first.manifest.image} -> ${second.manifest.image}`,
    imageDigest: first.manifest.imageDigest,
    compute: {
      gpu: first.manifest.compute.gpu,
      gpuCount: Math.max(first.manifest.compute.gpuCount, second.manifest.compute.gpuCount),
      cpuCores: Math.max(first.manifest.compute.cpuCores, second.manifest.compute.cpuCores),
      memoryGb: Math.max(first.manifest.compute.memoryGb, second.manifest.compute.memoryGb),
      estSecondsPerDesign:
        first.manifest.compute.estSecondsPerDesign + second.manifest.compute.estSecondsPerDesign,
    },
    composes: [first.manifest.id, second.manifest.id],
  };

  class ComposedAdapter extends Adapter {
    manifest = composedManifest;

    override validate(req: DesignRequest): ValidationError[] {
      return first.validate(req);
    }

    override async prepare(req: DesignRequest, workdir: string): Promise<PreparedJob> {
      const stageAWorkdir = `${workdir}/stage-0-${first.manifest.id}`;
      const stageBWorkdir = `${workdir}/stage-1-${second.manifest.id}`;
      const preparedA = await first.prepare(req, stageAWorkdir);
      const preparedB = await second.prepare(req, stageBWorkdir);

      const stages: PreparedStage[] = [
        toStage(first.manifest.id, preparedA),
        toStage(second.manifest.id, preparedB),
      ];

      return {
        workdir,
        inputsDir: preparedA.inputsDir,
        outputsDir: preparedB.outputsDir,
        requestPath: preparedA.requestPath,
        targetPath: preparedA.targetPath,
        toolArtifacts: {
          stage0: preparedA.toolArtifacts,
          stage1: preparedB.toolArtifacts,
        },
        stages,
      };
    }

    override async run(job: PreparedJob): Promise<RawOutput> {
      if (!job.stages || job.stages.length !== 2) {
        throw new Error(
          `ComposedAdapter[${this.manifest.id}].run: expected 2 stages, got ${job.stages?.length ?? 0}`,
        );
      }

      const jobA = reassembleJob(job.workdir, job.stages[0]!);
      const rawA = await first.run(jobA);
      const parsedA = await first.parse(rawA);

      const jobB = reassembleJob(job.workdir, job.stages[1]!);
      // Pass upstream designs to downstream via a tool-artifact slot; downstream
      // adapters that care about composition read `upstreamDesigns`.
      jobB.toolArtifacts = {
        ...jobB.toolArtifacts,
        upstreamDesigns: parsedA.designs,
        upstreamTool: first.manifest.id,
      };
      const rawB = await second.run(jobB);

      const parsedB = await second.parse(rawB);

      const composedRaw: ComposedRawOutput = {
        outputDir: rawB.outputDir,
        exitCode: rawA.exitCode === 0 ? rawB.exitCode : rawA.exitCode,
        stdout: `${rawA.stdout}\n---\n${rawB.stdout}`,
        stderr: `${rawA.stderr}\n---\n${rawB.stderr}`,
        stageOutputs: [
          { toolId: first.manifest.id, raw: rawA, parsed: parsedA },
          { toolId: second.manifest.id, raw: rawB, parsed: parsedB },
        ],
      };
      return composedRaw;
    }

    override async parse(raw: RawOutput): Promise<DesignResult> {
      const composed = raw as ComposedRawOutput;
      if (!composed.stageOutputs || composed.stageOutputs.length === 0) {
        throw new Error(
          `ComposedAdapter[${this.manifest.id}].parse: raw.stageOutputs missing — did run() produce it?`,
        );
      }
      const last = composed.stageOutputs[composed.stageOutputs.length - 1]!;
      return {
        designs: last.parsed.designs,
        runMetadata: {
          ...last.parsed.runMetadata,
          tool: this.manifest.id,
          stages: composed.stageOutputs.map((s) => s.toolId),
          adapterVersion: this.manifest.adapterVersion,
        },
      };
    }
  }

  return new ComposedAdapter();
}

function pickStricterTier(a: ToolManifest['tier'], b: ToolManifest['tier']): ToolManifest['tier'] {
  const rank: Record<ToolManifest['tier'], number> = {
    open: 0,
    'open-weights': 1,
    frontier: 2,
  };
  return rank[a] >= rank[b] ? a : b;
}

function toStage(toolId: string, job: PreparedJob): PreparedStage {
  return {
    toolId,
    requestPath: job.requestPath,
    inputsDir: job.inputsDir,
    outputsDir: job.outputsDir,
    toolArtifacts: job.toolArtifacts,
  };
}

function reassembleJob(workdir: string, stage: PreparedStage): PreparedJob {
  return {
    workdir,
    inputsDir: stage.inputsDir,
    outputsDir: stage.outputsDir,
    requestPath: stage.requestPath,
    targetPath: `${stage.inputsDir}/target.pdb`,
    toolArtifacts: { ...stage.toolArtifacts },
  };
}
