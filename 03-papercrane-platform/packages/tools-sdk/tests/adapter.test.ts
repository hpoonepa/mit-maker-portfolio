import { describe, it, expect } from 'vitest';
import { Adapter, RemoteAdapter } from '../src/adapter';
import type { DesignRequest, PreparedJob, RawOutput, DesignResult, ToolManifest } from '../src/types';

const validManifest: ToolManifest = {
  id: 'test-tool',
  displayName: 'Test Tool',
  version: '1.0.0',
  adapterVersion: 'a1',
  category: 'binder_design',
  tier: 'open',
  license: 'MIT',
  image: 'ghcr.io/papercrane/test:1.0.0-a1',
  imageDigest: 'sha256:0000000000000000000000000000000000000000000000000000000000000000',
  compute: {
    gpu: 'A100-40GB',
    gpuCount: 1,
    cpuCores: 8,
    memoryGb: 32,
    estSecondsPerDesign: 60,
  },
};

class TestAdapter extends Adapter {
  manifest = validManifest;
  prepareCalls = 0;
  runCalls = 0;
  parseCalls = 0;

  async prepare(req: DesignRequest, workdir: string): Promise<PreparedJob> {
    this.prepareCalls++;
    return {
      workdir,
      inputsDir: `${workdir}/inputs`,
      outputsDir: `${workdir}/outputs`,
      requestPath: `${workdir}/inputs/request.json`,
      targetPath: `${workdir}/inputs/target.pdb`,
      toolArtifacts: { cfg: 'cfg.json' },
    };
  }

  async run(job: PreparedJob): Promise<RawOutput> {
    this.runCalls++;
    return { outputDir: job.outputsDir, exitCode: 0, stdout: '', stderr: '' };
  }

  async parse(_raw: RawOutput): Promise<DesignResult> {
    this.parseCalls++;
    return {
      designs: [
        {
          structurePath: 's3://bucket/design1.pdb',
          sequence: 'MAGIC',
          metrics: { iptm: 0.85 },
          seed: 42,
        },
      ],
      runMetadata: { tool: 'test-tool', adapterVersion: 'a1' },
    };
  }
}

describe('Adapter', () => {
  it('exposes the provided manifest', () => {
    const a = new TestAdapter();
    expect(a.manifest.id).toBe('test-tool');
    expect(a.manifest.tier).toBe('open');
  });

  it('calls prepare/run/parse in sequence', async () => {
    const a = new TestAdapter();
    const req: DesignRequest = {
      targetPdb: 's3://bucket/target.pdb',
      seeds: [1, 2, 3],
      numDesigns: 3,
    };
    const prepared = await a.prepare(req, '/tmp/work-abc');
    expect(a.prepareCalls).toBe(1);
    const raw = await a.run(prepared);
    expect(a.runCalls).toBe(1);
    const result = await a.parse(raw);
    expect(a.parseCalls).toBe(1);
    expect(result.designs).toHaveLength(1);
  });

  it('provides a default validate() that accepts a valid request', () => {
    const a = new TestAdapter();
    const req: DesignRequest = {
      targetPdb: 's3://bucket/target.pdb',
      seeds: [1],
      numDesigns: 1,
    };
    expect(a.validate(req)).toEqual([]);
  });

  it('abstract methods reject if subclass forgets to implement', async () => {
    class BrokenAdapter extends Adapter {
      manifest = validManifest;
    }
    const b = new BrokenAdapter() as unknown as Adapter;
    // TypeScript can't enforce this at runtime without explicit abstract checks; we rely on the
    // abstract keyword at compile time. But at runtime, calling the missing methods should throw.
    await expect(
      (b as unknown as { prepare: () => Promise<unknown> }).prepare(),
    ).rejects.toThrow('prepare() is not implemented');
  });
});

describe('RemoteAdapter', () => {
  class TestRemoteAdapter extends RemoteAdapter {
    manifest: ToolManifest = { ...validManifest, tier: 'frontier', id: 'remote-test' };
    lastCalled: string | null = null;

    async prepare(req: DesignRequest, workdir: string): Promise<PreparedJob> {
      return {
        workdir,
        inputsDir: `${workdir}/inputs`,
        outputsDir: `${workdir}/outputs`,
        requestPath: `${workdir}/inputs/request.json`,
        targetPath: `${workdir}/inputs/target.pdb`,
        toolArtifacts: {},
      };
    }

    async run(_job: PreparedJob): Promise<RawOutput> {
      this.lastCalled = this.endpoint;
      return { outputDir: '/remote', exitCode: 0, stdout: '', stderr: '' };
    }

    async parse(_raw: RawOutput): Promise<DesignResult> {
      return { designs: [], runMetadata: { tool: 'remote-test' } };
    }
  }

  it('exposes an endpoint and an httpClient for subclasses', () => {
    const r = new TestRemoteAdapter({
      endpoint: 'https://api.example.com/v1/run',
      apiKey: 'test-key',
    });
    expect(r.endpoint).toBe('https://api.example.com/v1/run');
    expect(r.getHttpClient()).toBeDefined();
    expect(typeof r.getHttpClient().request).toBe('function');
  });

  it('run() uses the configured endpoint', async () => {
    const r = new TestRemoteAdapter({
      endpoint: 'https://api.example.com/v1/run',
      apiKey: 'test-key',
    });
    await r.run({
      workdir: '/tmp/w',
      inputsDir: '/tmp/w/inputs',
      outputsDir: '/tmp/w/outputs',
      requestPath: '/tmp/w/inputs/request.json',
      targetPath: '/tmp/w/inputs/target.pdb',
      toolArtifacts: {},
    });
    expect(r.lastCalled).toBe('https://api.example.com/v1/run');
  });
});
