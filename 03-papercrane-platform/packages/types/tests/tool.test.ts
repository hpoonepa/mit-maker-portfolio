import { describe, it, expect } from 'vitest';
import {
  ToolManifestSchema,
  ToolTierSchema,
  ToolCategorySchema,
  ComputeProfileSchema,
} from '../src/tool.js';

describe('ToolTierSchema', () => {
  it('accepts valid tiers', () => {
    expect(ToolTierSchema.parse('free')).toBe('free');
    expect(ToolTierSchema.parse('pro')).toBe('pro');
    expect(ToolTierSchema.parse('frontier')).toBe('frontier');
  });

  it('rejects invalid tier', () => {
    expect(() => ToolTierSchema.parse('enterprise')).toThrow();
  });
});

describe('ToolCategorySchema', () => {
  it('accepts valid categories', () => {
    const categories = [
      'binder-design',
      'structure-prediction',
      'sequence-design',
      'validation',
      'utility',
    ];
    for (const c of categories) {
      expect(ToolCategorySchema.parse(c)).toBe(c);
    }
  });

  it('rejects invalid category', () => {
    expect(() => ToolCategorySchema.parse('random')).toThrow();
  });
});

describe('ComputeProfileSchema', () => {
  it('accepts a minimal profile', () => {
    const parsed = ComputeProfileSchema.parse({
      gpuType: 'A100-80GB',
      gpuCount: 1,
      memoryGb: 80,
      estimatedMinutes: 30,
    });
    expect(parsed.gpuType).toBe('A100-80GB');
  });

  it('rejects zero gpuCount', () => {
    expect(() =>
      ComputeProfileSchema.parse({
        gpuType: 'A100-80GB',
        gpuCount: 0,
        memoryGb: 80,
        estimatedMinutes: 30,
      }),
    ).toThrow();
  });

  it('rejects unknown keys (.strict())', () => {
    expect(() =>
      ComputeProfileSchema.parse({
        gpuType: 'A100-80GB',
        gpuCount: 1,
        memoryGb: 80,
        estimatedMinutes: 30,
        extra: 'x',
      } as unknown),
    ).toThrow();
  });
});

describe('ToolManifestSchema', () => {
  const base = {
    toolId: 'bindcraft',
    name: 'BindCraft',
    version: '1.2.0',
    category: 'binder-design',
    tier: 'pro',
    description: 'End-to-end binder hallucination.',
    inputSchemaRef: 'DesignRequest',
    outputSchemaRef: 'DesignResult',
    compute: {
      gpuType: 'A100-80GB',
      gpuCount: 1,
      memoryGb: 80,
      estimatedMinutes: 45,
    },
    seedCostPerDesign: 1,
  };

  it('accepts a valid manifest', () => {
    const parsed = ToolManifestSchema.parse(base);
    expect(parsed.toolId).toBe('bindcraft');
  });

  it('rejects invalid tool id format (uppercase/spaces)', () => {
    expect(() =>
      ToolManifestSchema.parse({ ...base, toolId: 'BindCraft' }),
    ).toThrow();
    expect(() =>
      ToolManifestSchema.parse({ ...base, toolId: 'bind craft' }),
    ).toThrow();
  });

  it('rejects negative seed cost', () => {
    expect(() =>
      ToolManifestSchema.parse({ ...base, seedCostPerDesign: -1 }),
    ).toThrow();
  });

  it('rejects unknown keys (.strict())', () => {
    expect(() =>
      ToolManifestSchema.parse({ ...base, rogue: true } as unknown),
    ).toThrow();
  });
});
