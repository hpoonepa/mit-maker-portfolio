import { describe, it, expect } from 'vitest';
import { promises as fs } from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';
import { toolManifestSchema, parseManifest, loadManifest } from '../src/manifest';

const validManifest = {
  id: 'bindcraft',
  displayName: 'BindCraft',
  version: '1.2.0',
  adapterVersion: 'a3',
  category: 'binder_design',
  tier: 'open',
  license: 'MIT',
  image: 'ghcr.io/papercrane/bindcraft:1.2.0-cuda12.1-a3',
  imageDigest: 'sha256:8f2e8f2e8f2e8f2e8f2e8f2e8f2e8f2e8f2e8f2e8f2e8f2e8f2e8f2e8f2e8f2e',
  compute: {
    gpu: 'A100-40GB',
    gpuCount: 1,
    cpuCores: 8,
    memoryGb: 32,
    estSecondsPerDesign: 140,
  },
  defaultParams: { binder_length_range: [60, 150] },
  composes: ['proteinmpnn'],
};

describe('toolManifestSchema', () => {
  it('parses a valid manifest', () => {
    const parsed = toolManifestSchema.parse(validManifest);
    expect(parsed.id).toBe('bindcraft');
    expect(parsed.compute.gpuCount).toBe(1);
  });

  it('accepts a remote/frontier tier manifest without image compute', () => {
    const remoteManifest = {
      ...validManifest,
      id: 'af3',
      tier: 'frontier',
      transport: { type: 'https', endpoint: 'https://api.alphafold.example/v3/run' },
    };
    const parsed = toolManifestSchema.parse(remoteManifest);
    expect(parsed.tier).toBe('frontier');
    expect(parsed.transport?.type).toBe('https');
  });

  it('accepts the Modal transport used by production tool runners', () => {
    const modalManifest = {
      ...validManifest,
      id: 'alphafold3',
      category: 'structure_prediction',
      tier: 'frontier',
      licenseGate: false,
      transport: {
        type: 'modal',
        app: 'alphafold3',
        function: 'papercrane_dispatch',
      },
    };
    const parsed = toolManifestSchema.parse(modalManifest);
    expect(parsed.transport).toEqual({
      type: 'modal',
      app: 'alphafold3',
      function: 'papercrane_dispatch',
    });
  });

  it('rejects a manifest missing required fields', () => {
    const bad = { ...validManifest };
    delete (bad as Record<string, unknown>).id;
    expect(() => toolManifestSchema.parse(bad)).toThrow();
  });

  it('rejects an invalid tier', () => {
    const bad = { ...validManifest, tier: 'not-a-tier' };
    expect(() => toolManifestSchema.parse(bad)).toThrow();
  });

  it('rejects a malformed image digest', () => {
    const bad = { ...validManifest, imageDigest: 'not-a-digest' };
    expect(() => toolManifestSchema.parse(bad)).toThrow();
  });
});

describe('parseManifest', () => {
  it('returns a typed manifest when input is valid', () => {
    const m = parseManifest(JSON.stringify(validManifest));
    expect(m.id).toBe('bindcraft');
  });

  it('throws on invalid JSON', () => {
    expect(() => parseManifest('{bad json')).toThrow();
  });
});

describe('loadManifest', () => {
  it('loads a manifest.json from disk', async () => {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'pc-manifest-'));
    const p = path.join(dir, 'manifest.json');
    await fs.writeFile(p, JSON.stringify(validManifest));
    const m = await loadManifest(p);
    expect(m.id).toBe('bindcraft');
    expect(m.adapterVersion).toBe('a3');
    await fs.rm(dir, { recursive: true, force: true });
  });

  it('throws a descriptive error when the file does not exist', async () => {
    await expect(loadManifest('/nonexistent/path/manifest.json')).rejects.toThrow();
  });

  it('throws when the file contains invalid manifest data', async () => {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'pc-manifest-'));
    const p = path.join(dir, 'manifest.json');
    await fs.writeFile(p, JSON.stringify({ id: 'x' }));
    await expect(loadManifest(p)).rejects.toThrow();
    await fs.rm(dir, { recursive: true, force: true });
  });

  it.each([
    'bindcraft',
    'proteinmpnn',
    'rfdiffusion',
    'boltz1',
    'boltz2',
    'chai1',
    'ligandmpnn',
    'solublempnn',
    'esm2',
    'boltzgen',
    'chroma',
    'alphafold3',
  ])('loads the shipped %s manifest', async (toolId) => {
    const manifestPath = path.resolve(__dirname, '..', '..', '..', 'tools', toolId, 'manifest.json');
    const manifest = await loadManifest(manifestPath);
    expect(manifest.id).toBe(toolId);
  });
});
