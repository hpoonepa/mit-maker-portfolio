import { describe, it, expect } from 'vitest';
import { validateMetrics } from '../../src/metrics/validate';

/**
 * validateMetrics — the worker persist boundary's metric guard.
 *
 * Contract under test:
 *   - canonicalises lowercase/aliased keys the adapters emit
 *   - drops (does not null-fill) out-of-range known metrics, with a warning
 *   - preserves unknown keys and non-numeric passthrough values verbatim
 *   - never hard-fails: always returns a metrics object + valid flag + warnings
 */

describe('validateMetrics — canonical casing', () => {
  it('rewrites lowercase/aliased keys to canonical labels', () => {
    const { metrics } = validateMetrics({
      iptm: 0.8,
      ipsae: 0.7,
      plddt: 85,
      plddt_mean: 90, // alias collides with plddt → canonical pLDDT wins (last)
      pae: 12,
      ipae_mean: 9,
      pdockq: 0.55,
      ptm: 0.6,
      dockq: 0.5,
    });
    expect(metrics.ipTM).toBe(0.8);
    expect(metrics.ipSAE).toBe(0.7);
    expect(metrics.pDockQ).toBe(0.55);
    expect(metrics.pTM).toBe(0.6);
    expect(metrics.DockQ).toBe(0.5);
    // canonical labels present, raw aliases gone
    expect(metrics.pLDDT).toBeTypeOf('number');
    expect(metrics.pAE).toBeTypeOf('number');
    expect(metrics).not.toHaveProperty('iptm');
    expect(metrics).not.toHaveProperty('ipsae');
    expect(metrics).not.toHaveProperty('plddt');
  });

  it('passes already-canonical keys through unchanged', () => {
    const { metrics, valid, warnings } = validateMetrics({ ipTM: 0.9, pLDDT: 70 });
    expect(metrics.ipTM).toBe(0.9);
    expect(metrics.pLDDT).toBe(70);
    expect(valid).toBe(true);
    expect(warnings).toHaveLength(0);
  });
});

describe('validateMetrics — range checks', () => {
  it('drops out-of-range unit metrics ([0,1]) and warns', () => {
    const { metrics, valid, warnings } = validateMetrics({
      iptm: 1.4, // out of [0,1]
      ipsae: -0.2, // out of [0,1]
      pdockq: 0.5, // in range
    });
    expect(metrics).not.toHaveProperty('ipTM');
    expect(metrics).not.toHaveProperty('ipSAE');
    expect(metrics.pDockQ).toBe(0.5);
    expect(valid).toBe(false);
    expect(warnings.length).toBe(2);
    expect(warnings.join(' ')).toMatch(/ipTM/);
    expect(warnings.join(' ')).toMatch(/ipSAE/);
  });

  it('drops pLDDT outside [0,100] and pAE below 0', () => {
    const { metrics, warnings } = validateMetrics({
      plddt: 140,
      pae: -3,
    });
    expect(metrics).not.toHaveProperty('pLDDT');
    expect(metrics).not.toHaveProperty('pAE');
    expect(warnings.length).toBe(2);
  });

  it('keeps pAE at the lower bound and large positive values', () => {
    const { metrics, valid } = validateMetrics({ pae: 0, plddt: 100, iptm: 1, ipsae: 0 });
    expect(metrics.pAE).toBe(0);
    expect(metrics.pLDDT).toBe(100);
    expect(metrics.ipTM).toBe(1);
    expect(metrics.ipSAE).toBe(0);
    expect(valid).toBe(true);
  });

  it('drops non-finite known metrics (NaN/Infinity) with a warning', () => {
    const { metrics, warnings } = validateMetrics({
      iptm: Number.NaN,
      ipsae: Number.POSITIVE_INFINITY,
    });
    expect(metrics).not.toHaveProperty('ipTM');
    expect(metrics).not.toHaveProperty('ipSAE');
    expect(warnings.length).toBe(2);
  });
});

describe('validateMetrics — passthrough', () => {
  it('preserves unknown numeric keys verbatim', () => {
    const { metrics, valid } = validateMetrics({ composite: 0.42, interfaceSC: 0.78 });
    expect(metrics.composite).toBe(0.42);
    expect(metrics.interfaceSC).toBe(0.78);
    expect(valid).toBe(true);
  });

  it('preserves non-numeric passthrough values like provenance and sequence', () => {
    const { metrics } = validateMetrics({
      iptm: 0.8,
      provenance: 'stub',
      sequence: 'MKTAYIAK',
      length: 8,
      cifFallbackPdb: '1CRN',
    });
    expect(metrics.ipTM).toBe(0.8);
    expect(metrics.provenance).toBe('stub');
    expect(metrics.sequence).toBe('MKTAYIAK');
    expect(metrics.length).toBe(8);
    expect(metrics.cifFallbackPdb).toBe('1CRN');
  });

  it('handles empty / nullish input without throwing', () => {
    expect(validateMetrics({}).valid).toBe(true);
    expect(validateMetrics(undefined).valid).toBe(true);
    expect(validateMetrics(null).metrics).toEqual({});
  });
});
