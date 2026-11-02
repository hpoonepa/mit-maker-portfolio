import { describe, it, expect } from 'vitest';
import {
  TargetSchema,
  TargetClassSchema,
  TargetTierSchema,
} from '../src/target.js';

describe('TargetClassSchema', () => {
  it('accepts valid classes', () => {
    const classes = [
      'receptor',
      'enzyme',
      'antibody',
      'transcription-factor',
      'peptide',
      'other',
    ];
    for (const c of classes) {
      expect(TargetClassSchema.parse(c)).toBe(c);
    }
  });

  it('rejects unknown class', () => {
    expect(() => TargetClassSchema.parse('alien')).toThrow();
  });
});

describe('TargetTierSchema', () => {
  it('accepts valid tiers', () => {
    expect(TargetTierSchema.parse('easy')).toBe('easy');
    expect(TargetTierSchema.parse('medium')).toBe('medium');
    expect(TargetTierSchema.parse('hard')).toBe('hard');
  });

  it('rejects unknown tier', () => {
    expect(() => TargetTierSchema.parse('impossible')).toThrow();
  });
});

describe('TargetSchema', () => {
  const base = {
    id: '550e8400-e29b-41d4-a716-446655440000',
    slug: 'pd-l1',
    name: 'PD-L1',
    pdbId: '5J89',
    chain: 'A',
    class: 'receptor',
    tier: 'medium',
    hotspots: [{ chain: 'A', residues: [54, 56, 115] }],
    createdAt: '2026-04-23T10:00:00.000Z',
  };

  it('accepts a valid target', () => {
    const parsed = TargetSchema.parse(base);
    expect(parsed.slug).toBe('pd-l1');
  });

  it('rejects bad slug (uppercase, spaces)', () => {
    expect(() =>
      TargetSchema.parse({ ...base, slug: 'PD L1' }),
    ).toThrow();
    expect(() =>
      TargetSchema.parse({ ...base, slug: 'PD-L1' }),
    ).toThrow();
  });

  it('rejects pdbId with wrong length', () => {
    expect(() => TargetSchema.parse({ ...base, pdbId: '5J8' })).toThrow();
    expect(() => TargetSchema.parse({ ...base, pdbId: '5J8911' })).toThrow();
  });

  it('passes through additional persistence fields', () => {
    const parsed = TargetSchema.parse({ ...base, orgId: 'org-1' });
    expect(parsed.orgId).toBe('org-1');
  });
});
