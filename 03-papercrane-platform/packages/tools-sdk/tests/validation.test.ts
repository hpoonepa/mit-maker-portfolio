import { describe, it, expect } from 'vitest';
import { defaultValidate } from '../src/validation';
import type { DesignRequest } from '../src/types';

const base: DesignRequest = {
  targetPdb: 's3://bucket/target.pdb',
  seeds: [1, 2, 3],
  numDesigns: 3,
};

describe('defaultValidate', () => {
  it('accepts a minimal valid request', () => {
    expect(defaultValidate(base)).toEqual([]);
  });

  it('rejects a request with no targetPdb', () => {
    const errs = defaultValidate({ ...base, targetPdb: '' });
    expect(errs.length).toBeGreaterThan(0);
    expect(errs[0]?.field).toBe('targetPdb');
  });

  it('rejects a request with an empty seeds array', () => {
    const errs = defaultValidate({ ...base, seeds: [] });
    expect(errs.some((e) => e.field === 'seeds')).toBe(true);
  });

  it('rejects a request with a seed outside the allowed uint32 range', () => {
    const errs = defaultValidate({ ...base, seeds: [-1, 2 ** 32] });
    expect(errs.some((e) => e.field === 'seeds')).toBe(true);
  });

  it('rejects a request with non-integer seeds', () => {
    const errs = defaultValidate({ ...base, seeds: [1.5] });
    expect(errs.some((e) => e.field === 'seeds')).toBe(true);
  });

  it('rejects duplicate seeds and a mismatched design count', () => {
    const duplicate = defaultValidate({ ...base, seeds: [1, 1, 2] });
    expect(duplicate.some((e) => e.message === 'seeds must be unique')).toBe(true);

    const mismatch = defaultValidate({ ...base, numDesigns: 4 });
    expect(mismatch.some((e) => e.field === 'numDesigns')).toBe(true);
  });

  it('rejects a request with numDesigns <= 0', () => {
    const errs = defaultValidate({ ...base, numDesigns: 0 });
    expect(errs.some((e) => e.field === 'numDesigns')).toBe(true);
  });

  it('rejects malformed hotspots (bad chain, missing resi)', () => {
    const errs = defaultValidate({
      ...base,
      hotspots: [
        { chain: '', resi: 12 },
        { chain: 'A', resi: -1 },
        { chain: 'AB', resi: 5 },
      ],
    });
    expect(errs.filter((e) => e.field.startsWith('hotspots')).length).toBeGreaterThanOrEqual(3);
  });

  it('accepts valid hotspots', () => {
    const errs = defaultValidate({
      ...base,
      hotspots: [
        { chain: 'A', resi: 12 },
        { chain: 'B', resi: 34 },
      ],
    });
    expect(errs).toEqual([]);
  });

  it('rejects invalid lengthRange (max < min)', () => {
    const errs = defaultValidate({
      ...base,
      constraints: { lengthRange: [100, 50] },
    });
    expect(errs.some((e) => e.field === 'constraints.lengthRange')).toBe(true);
  });

  it('rejects negative lengths in lengthRange', () => {
    const errs = defaultValidate({
      ...base,
      constraints: { lengthRange: [-1, 50] },
    });
    expect(errs.some((e) => e.field === 'constraints.lengthRange')).toBe(true);
  });
});
