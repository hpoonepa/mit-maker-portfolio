import { describe, it, expect } from 'vitest';
import {
  DesignRequestSchema,
  DesignResultSchema,
  DesignMetricsSchema,
  HotspotSchema,
} from '../src/design.js';

describe('HotspotSchema', () => {
  it('accepts single-character chain and positive residue indices', () => {
    const parsed = HotspotSchema.parse({ chain: 'A', residues: [12, 13, 14] });
    expect(parsed.chain).toBe('A');
    expect(parsed.residues).toEqual([12, 13, 14]);
  });

  it('rejects chain of length != 1', () => {
    expect(() => HotspotSchema.parse({ chain: 'AB', residues: [1] })).toThrow();
    expect(() => HotspotSchema.parse({ chain: '', residues: [1] })).toThrow();
  });

  it('rejects non-integer residues', () => {
    expect(() => HotspotSchema.parse({ chain: 'A', residues: [1.5] })).toThrow();
  });

  it('rejects unknown keys (.strict())', () => {
    expect(() =>
      HotspotSchema.parse({ chain: 'A', residues: [1], extra: 'nope' } as unknown),
    ).toThrow();
  });
});

describe('DesignRequestSchema', () => {
  const base = {
    targetPdb: '7K3Q',
    seeds: [0, 1, 2],
    numDesigns: 3,
  };

  it('accepts a minimal valid request', () => {
    const parsed = DesignRequestSchema.parse(base);
    expect(parsed.numDesigns).toBe(3);
  });

  it('accepts a full request with hotspots and constraints', () => {
    const parsed = DesignRequestSchema.parse({
      ...base,
      hotspots: [{ chain: 'A', residues: [10, 11] }],
      constraints: {
        lengthRange: [60, 120],
        disulfides: false,
        solubility: 'strict',
      },
      toolParams: { num_recycles: 3 },
    });
    expect(parsed.hotspots?.[0]?.chain).toBe('A');
    expect(parsed.constraints?.lengthRange).toEqual([60, 120]);
  });

  it('rejects negative seeds', () => {
    expect(() =>
      DesignRequestSchema.parse({ ...base, seeds: [-1] }),
    ).toThrow();
  });

  it('rejects duplicate seeds', () => {
    expect(() =>
      DesignRequestSchema.parse({ ...base, seeds: [1, 1, 2] }),
    ).toThrow(/seeds must be unique/i);
  });

  it('rejects seeds outside the uint32 range used by model runtimes', () => {
    expect(() =>
      DesignRequestSchema.parse({ ...base, seeds: [0x1_0000_0000] }),
    ).toThrow();
  });

  it('rejects a design count that does not match the seed list', () => {
    expect(() =>
      DesignRequestSchema.parse({ ...base, numDesigns: 4 }),
    ).toThrow(/numDesigns must match the number of seeds/i);
  });

  it('rejects zero or negative numDesigns', () => {
    expect(() =>
      DesignRequestSchema.parse({ ...base, numDesigns: 0 }),
    ).toThrow();
    expect(() =>
      DesignRequestSchema.parse({ ...base, numDesigns: -5 }),
    ).toThrow();
  });

  it('rejects unknown keys (.strict())', () => {
    expect(() =>
      DesignRequestSchema.parse({ ...base, bogus: true } as unknown),
    ).toThrow();
  });
});

describe('DesignMetricsSchema', () => {
  it('accepts arbitrary numeric metrics', () => {
    const parsed = DesignMetricsSchema.parse({
      ipsae: 0.83,
      iptm: 0.67,
      plddt: 85.2,
    });
    expect(parsed.ipsae).toBe(0.83);
  });

  it('rejects non-numeric metric values', () => {
    expect(() =>
      DesignMetricsSchema.parse({ ipsae: 'high' } as unknown),
    ).toThrow();
  });
});

describe('DesignResultSchema', () => {
  const base = {
    id: '550e8400-e29b-41d4-a716-446655440000',
    jobId: '550e8400-e29b-41d4-a716-446655440001',
    sequence: 'MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ',
    length: 33,
    seed: 42,
    metrics: { ipsae: 0.81 },
    createdAt: '2026-04-23T10:00:00.000Z',
  };

  it('accepts a minimal valid result', () => {
    const parsed = DesignResultSchema.parse(base);
    expect(parsed.seed).toBe(42);
  });

  it('rejects non-UUID ids', () => {
    expect(() =>
      DesignResultSchema.parse({ ...base, id: 'not-a-uuid' }),
    ).toThrow();
  });

  it('rejects non-ISO createdAt', () => {
    expect(() =>
      DesignResultSchema.parse({ ...base, createdAt: '2026-04-23' }),
    ).toThrow();
  });

  it('rejects unknown keys (.strict())', () => {
    expect(() =>
      DesignResultSchema.parse({ ...base, rogue: 1 } as unknown),
    ).toThrow();
  });
});
