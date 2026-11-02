import { mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { RESERVED_IDS, ValidationError, validateToolName } from '../src/validate.js';

describe('validateToolName', () => {
  let repoRoot: string;

  beforeEach(() => {
    repoRoot = mkdtempSync(join(tmpdir(), 'papercrane-cli-validate-'));
    mkdirSync(join(repoRoot, 'tools'), { recursive: true });
  });

  afterEach(() => {
    rmSync(repoRoot, { recursive: true, force: true });
  });

  it('accepts a valid slug', () => {
    expect(validateToolName('mynewtool', { repoRoot })).toBe('mynewtool');
    expect(validateToolName('my-new-tool', { repoRoot })).toBe('my-new-tool');
    expect(validateToolName('tool123', { repoRoot })).toBe('tool123');
  });

  it('rejects empty / non-string names', () => {
    expect(() => validateToolName('', { repoRoot })).toThrow(ValidationError);
    // @ts-expect-error — deliberately bad input
    expect(() => validateToolName(undefined, { repoRoot })).toThrow(ValidationError);
  });

  it('rejects names with uppercase or invalid chars', () => {
    expect(() => validateToolName('MyTool', { repoRoot })).toThrow(/invalid tool id/);
    expect(() => validateToolName('my_tool', { repoRoot })).toThrow(/invalid tool id/);
    expect(() => validateToolName('my tool', { repoRoot })).toThrow(/invalid tool id/);
    expect(() => validateToolName('-leading', { repoRoot })).toThrow(/invalid tool id/);
    expect(() => validateToolName('1starts-digit', { repoRoot })).toThrow(/invalid tool id/);
  });

  it('rejects names that are too short or too long', () => {
    expect(() => validateToolName('ab', { repoRoot })).toThrow(/invalid tool id/);
    expect(() => validateToolName('a'.repeat(32), { repoRoot })).toThrow(/invalid tool id/);
  });

  it('rejects every reserved id', () => {
    for (const reserved of RESERVED_IDS) {
      expect(() => validateToolName(reserved, { repoRoot })).toThrow(/reserved/);
    }
  });

  it('rejects a collision with an existing tool dir', () => {
    mkdirSync(join(repoRoot, 'tools', 'mynewtool'), { recursive: true });
    expect(() => validateToolName('mynewtool', { repoRoot })).toThrow(/already exists/);
  });

  it('trims surrounding whitespace before validating', () => {
    expect(validateToolName('  spaced  ', { repoRoot })).toBe('spaced');
  });
});
