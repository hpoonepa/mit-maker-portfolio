import { execSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterAll, describe, expect, it } from 'vitest';

import { buildContext, generateScaffold } from '../src/generate.js';
import type { ScaffoldAnswers } from '../src/prompts.js';

const SAMPLE_ANSWERS: ScaffoldAnswers = {
  displayName: 'SmokeTool',
  category: 'binder_design',
  tier: 'open',
  license: 'MIT',
  gpu: 'A100-40GB',
  memoryGb: 32,
  estSeconds: 90,
  upstreamRepo: 'https://github.com/papercrane/smoketool',
  composes: ['bindcraft', 'proteinmpnn'],
};

describe('generateScaffold', () => {
  const tmp = mkdtempSync(join(tmpdir(), 'papercrane-cli-generate-'));

  afterAll(() => {
    rmSync(tmp, { recursive: true, force: true });
  });

  it('writes the full tool skeleton with every expected file', () => {
    const targetDir = join(tmp, 'tools', 'smoketool');
    const ctx = buildContext('smoketool', SAMPLE_ANSWERS, {
      now: new Date('2026-04-23T00:00:00Z'),
    });
    const { written } = generateScaffold(ctx, { targetDir });

    const expected = [
      'Dockerfile',
      'manifest.json',
      'adapter.py',
      'run.sh',
      'README.md',
      'requirements-dev.txt',
      'schemas/input.json',
      'schemas/output.json',
      'tests/test_adapter.py',
      'tests/test_manifest.py',
      'tests/fixtures/request.json',
      'tests/fixtures/target.pdb',
      'tests/fixtures/sample_output/design_0001.pdb',
      'tests/fixtures/sample_output/design_0001.json',
    ];
    for (const rel of expected) {
      expect(existsSync(join(targetDir, rel)), `missing ${rel}`).toBe(true);
    }
    // Every written path should be absolute and inside targetDir.
    for (const abs of written) {
      expect(abs.startsWith(targetDir)).toBe(true);
    }
    expect(written.length).toBe(expected.length);
  });

  it('renders manifest.json as valid JSON with expected fields', () => {
    const targetDir = join(tmp, 'tools', 'smoketool-json');
    const ctx = buildContext('smoketool-json', SAMPLE_ANSWERS);
    generateScaffold(ctx, { targetDir });

    const manifestPath = join(targetDir, 'manifest.json');
    const raw = readFileSync(manifestPath, 'utf8');
    const parsed = JSON.parse(raw);
    expect(parsed.id).toBe('smoketool-json');
    expect(parsed.displayName).toBe('SmokeTool');
    expect(parsed.category).toBe('binder_design');
    expect(parsed.tier).toBe('open');
    expect(parsed.license).toBe('MIT');
    expect(parsed.compute.gpu).toBe('A100-40GB');
    expect(parsed.compute.memoryGb).toBe(32);
    expect(parsed.compute.estSecondsPerDesign).toBe(90);
    expect(parsed.composes).toEqual(['bindcraft', 'proteinmpnn']);
    expect(parsed.inputSchema).toBe('schemas/input.json');
    expect(parsed.outputSchema).toBe('schemas/output.json');
  });

  it('renders schemas as valid JSON', () => {
    const targetDir = join(tmp, 'tools', 'smoketool-schemas');
    const ctx = buildContext('smoketool-schemas', SAMPLE_ANSWERS);
    generateScaffold(ctx, { targetDir });

    const input = JSON.parse(
      readFileSync(join(targetDir, 'schemas/input.json'), 'utf8'),
    );
    const output = JSON.parse(
      readFileSync(join(targetDir, 'schemas/output.json'), 'utf8'),
    );
    expect(input['$schema']).toBe('http://json-schema.org/draft-07/schema#');
    expect(output['$schema']).toBe('http://json-schema.org/draft-07/schema#');
    expect(output.properties.runMetadata.properties.tool.const).toBe(
      'smoketool-schemas',
    );
  });

  it('generates an adapter.py that compiles under python -m py_compile (best effort)', () => {
    const targetDir = join(tmp, 'tools', 'smoketool-py');
    const ctx = buildContext('smoketool-py', SAMPLE_ANSWERS);
    generateScaffold(ctx, { targetDir });

    const adapterPath = join(targetDir, 'adapter.py');
    expect(existsSync(adapterPath)).toBe(true);

    // Try `python -m py_compile` if available in PATH — skip on systems
    // without Python to keep the test suite portable.
    let hasPython = false;
    try {
      execSync('python3 --version', { stdio: 'ignore' });
      hasPython = true;
    } catch {
      hasPython = false;
    }
    if (!hasPython) return;
    expect(() =>
      execSync(`python3 -m py_compile "${adapterPath}"`, { stdio: 'pipe' }),
    ).not.toThrow();
  });

  it('ships the requested "tools/__smoke__/manifest.json" artifact', () => {
    const targetDir = join(tmp, 'tools', '__smoke__');
    const ctx = buildContext('smoketool-smoke', SAMPLE_ANSWERS);
    generateScaffold(ctx, { targetDir });

    const manifest = JSON.parse(
      readFileSync(join(targetDir, 'manifest.json'), 'utf8'),
    );
    expect(manifest.id).toBe('smoketool-smoke');
    // Sanity: directory is browsable end-to-end
    expect(existsSync(join(targetDir, 'adapter.py'))).toBe(true);
    expect(existsSync(join(targetDir, 'tests/test_adapter.py'))).toBe(true);
  });

  it('buildContext derives a safe Python class name from displayName', () => {
    const weird = buildContext('weird-tool', {
      ...SAMPLE_ANSWERS,
      displayName: 'Weird Tool 2!',
    });
    expect(weird.adapterClassName).toBe('WeirdTool2Adapter');
  });

  it('copies plain files (target.pdb, requirements-dev.txt) verbatim', () => {
    const targetDir = join(tmp, 'tools', 'smoketool-copy');
    const ctx = buildContext('smoketool-copy', SAMPLE_ANSWERS);
    generateScaffold(ctx, { targetDir });

    const req = readFileSync(join(targetDir, 'requirements-dev.txt'), 'utf8');
    expect(req).toContain('pytest');
    expect(req).toContain('jsonschema');

    const pdb = readFileSync(
      join(targetDir, 'tests/fixtures/target.pdb'),
      'utf8',
    );
    expect(pdb.startsWith('ATOM')).toBe(true);
    expect(pdb.trim().endsWith('END')).toBe(true);
    // Plain files have no unrendered Handlebars markers.
    expect(pdb).not.toContain('{{');
  });

  it('rendered output never contains unrendered Handlebars markers', () => {
    const targetDir = join(tmp, 'tools', 'smoketool-complete');
    const ctx = buildContext('smoketool-complete', SAMPLE_ANSWERS);
    const { written } = generateScaffold(ctx, { targetDir });
    for (const abs of written) {
      // Only check text files — PDBs were already covered above.
      if (abs.endsWith('.pdb')) continue;
      const contents = readFileSync(abs, 'utf8');
      expect(contents, `unrendered {{ }} in ${abs}`).not.toMatch(/{{\s*\w/);
    }
  });

  it('uses a custom templateRoot when provided', () => {
    const customRoot = mkdtempSync(join(tmp, 'tmpl-'));
    mkdirSync(join(customRoot, 'nested'), { recursive: true });
    writeFileSync(join(customRoot, 'greeting.txt.hbs'), 'hello {{id}}\n');
    writeFileSync(join(customRoot, 'nested', 'plain.txt'), 'plain\n');

    const targetDir = join(tmp, 'custom-out');
    const ctx = buildContext('custom-tool', SAMPLE_ANSWERS);
    generateScaffold(ctx, { targetDir, templateRoot: customRoot });

    expect(readFileSync(join(targetDir, 'greeting.txt'), 'utf8')).toBe(
      'hello custom-tool\n',
    );
    expect(readFileSync(join(targetDir, 'nested/plain.txt'), 'utf8')).toBe(
      'plain\n',
    );
  });
});
