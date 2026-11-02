import { describe, it, expect } from 'vitest';
import { Adapter } from '../src/adapter';
import { compose } from '../src/compose';
import type { DesignRequest, PreparedJob, RawOutput, DesignResult, ToolManifest } from '../src/types';

const manifestA: ToolManifest = {
  id: 'rfdiffusion',
  displayName: 'RFdiffusion',
  version: '1.1.0',
  adapterVersion: 'a1',
  category: 'backbone',
  tier: 'open',
  license: 'BSD-3',
  image: 'ghcr.io/papercrane/rfdiffusion:1.1.0-a1',
  imageDigest: 'sha256:' + 'a'.repeat(64),
  compute: { gpu: 'A100-40GB', gpuCount: 1, cpuCores: 8, memoryGb: 32, estSecondsPerDesign: 35 },
};

const manifestB: ToolManifest = {
  id: 'proteinmpnn',
  displayName: 'ProteinMPNN',
  version: '1.0.0',
  adapterVersion: 'a1',
  category: 'sequence',
  tier: 'open',
  license: 'MIT',
  image: 'ghcr.io/papercrane/proteinmpnn:1.0.0-a1',
  imageDigest: 'sha256:' + 'b'.repeat(64),
  compute: { gpu: 'A10', gpuCount: 1, cpuCores: 4, memoryGb: 16, estSecondsPerDesign: 4 },
};

class BackboneAdapter extends Adapter {
  manifest = manifestA;
  preparedWith: DesignRequest | null = null;
  async prepare(req: DesignRequest, workdir: string): Promise<PreparedJob> {
    this.preparedWith = req;
    return {
      workdir,
      inputsDir: `${workdir}/inputs`,
      outputsDir: `${workdir}/outputs`,
      requestPath: `${workdir}/inputs/request.json`,
      targetPath: `${workdir}/inputs/target.pdb`,
      toolArtifacts: { stage: 'backbone' },
    };
  }
  async run(job: PreparedJob): Promise<RawOutput> {
    return { outputDir: job.outputsDir, exitCode: 0, stdout: 'backbone done', stderr: '' };
  }
  async parse(_raw: RawOutput): Promise<DesignResult> {
    return {
      designs: [
        { structurePath: 's3://bucket/bb1.pdb', sequence: '', metrics: { rog: 14.2 }, seed: 1 },
        { structurePath: 's3://bucket/bb2.pdb', sequence: '', metrics: { rog: 13.8 }, seed: 2 },
      ],
      runMetadata: { tool: 'rfdiffusion', adapterVersion: 'a1' },
    };
  }
}

class SequenceAdapter extends Adapter {
  manifest = manifestB;
  preparedWith: DesignRequest | null = null;
  async prepare(req: DesignRequest, workdir: string): Promise<PreparedJob> {
    this.preparedWith = req;
    return {
      workdir,
      inputsDir: `${workdir}/inputs`,
      outputsDir: `${workdir}/outputs`,
      requestPath: `${workdir}/inputs/request.json`,
      targetPath: `${workdir}/inputs/target.pdb`,
      toolArtifacts: { stage: 'sequence' },
    };
  }
  async run(job: PreparedJob): Promise<RawOutput> {
    return { outputDir: job.outputsDir, exitCode: 0, stdout: 'sequence done', stderr: '' };
  }
  async parse(_raw: RawOutput): Promise<DesignResult> {
    return {
      designs: [
        { structurePath: 's3://bucket/bb1.pdb', sequence: 'SEQ1', metrics: { plddt: 0.9 }, seed: 1 },
        { structurePath: 's3://bucket/bb2.pdb', sequence: 'SEQ2', metrics: { plddt: 0.88 }, seed: 2 },
      ],
      runMetadata: { tool: 'proteinmpnn', adapterVersion: 'a1' },
    };
  }
}

describe('compose', () => {
  it('produces a composed adapter whose manifest reflects the chain', () => {
    const a = new BackboneAdapter();
    const b = new SequenceAdapter();
    const composed = compose(a, b);
    expect(composed.manifest.id).toBe('rfdiffusion+proteinmpnn');
    expect(composed.manifest.composes).toEqual(['rfdiffusion', 'proteinmpnn']);
    expect(composed.manifest.category).toBe('composite');
  });

  it('runs both adapters in sequence and returns the downstream result, carrying upstream metadata', async () => {
    const a = new BackboneAdapter();
    const b = new SequenceAdapter();
    const composed = compose(a, b);
    const req: DesignRequest = {
      targetPdb: 's3://bucket/target.pdb',
      seeds: [1, 2],
      numDesigns: 2,
    };
    const prepared = await composed.prepare(req, '/tmp/wd');
    expect(prepared.stages).toHaveLength(2);
    expect(prepared.stages?.[0]?.toolId).toBe('rfdiffusion');
    expect(prepared.stages?.[1]?.toolId).toBe('proteinmpnn');

    const raw = await composed.run(prepared);
    expect(raw.exitCode).toBe(0);

    const result = await composed.parse(raw);
    // Final designs come from the last stage (sequence)
    expect(result.designs).toHaveLength(2);
    expect(result.designs[0]?.sequence).toBe('SEQ1');
    // runMetadata carries both stage tools
    expect(result.runMetadata.tool).toBe('rfdiffusion+proteinmpnn');
    expect(result.runMetadata.stages).toEqual(['rfdiffusion', 'proteinmpnn']);
  });

  it('validates the request using the first adapter', () => {
    const a = new BackboneAdapter();
    const b = new SequenceAdapter();
    const composed = compose(a, b);
    const errs = composed.validate({
      targetPdb: '',
      seeds: [1],
      numDesigns: 1,
    });
    expect(errs.length).toBeGreaterThan(0);
  });
});
