import { describe, expect, it } from 'vitest';
import {
  LLM_META_SCORER_VERSION,
  scoreDesignWithLlmPrior,
} from '../src/scoring/llmMetaScorer.js';

describe('LLM meta scorer', () => {
  it('selects the exact 5G51 prior and scores only observed metrics', () => {
    const result = scoreDesignWithLlmPrior({
      pdbId: '5g51',
      targetName: 'Deformed wing virus VP3',
      metrics: {
        ipsae: 0.82,
        interfaceSC: 0.7,
        interface_residues: 24,
      },
    });

    expect(result.version).toBe(LLM_META_SCORER_VERSION);
    expect(result.evidenceType).toBe('computational');
    expect(result.priorSource).toBe('target_prior');
    expect(result.targetKey).toBe('5G51');
    expect(result.status).toBe('scored');
    expect(result.score).toBeGreaterThan(0.7);
    expect(result.coverage).toBeGreaterThan(0.5);
    expect(result.contributions.map((item) => item.metric)).toContain(
      'computational__boltz2_min_ipsae',
    );
  });

  it('scores canonical metric keys emitted by the computational pipeline', () => {
    const result = scoreDesignWithLlmPrior({
      targetName: 'EGFR',
      metrics: {
        computational__actifptm: 0.9,
        computational__interface_residues: 18,
        computational__boltz2_min_ipsae: 0.8,
      },
    });

    expect(result.status).toBe('scored');
    expect(result.availableMetrics).toBe(3);
    expect(result.contributions.map((item) => item.metric)).toEqual(
      expect.arrayContaining([
        'computational__actifptm',
        'computational__interface_residues',
        'computational__boltz2_min_ipsae',
      ]),
    );
  });

  it('matches target-name aliases without assigning ambiguous PDB identities', () => {
    const result = scoreDesignWithLlmPrior({
      targetName: 'PD-L1',
      pdbId: '9ZZZ',
      metrics: { ipTM: 0.74, ipsae: 0.68 },
    });

    expect(result.targetKey).toBe('PDL1');
    expect(result.priorSource).toBe('target_prior');
  });

  it('prefers exact PDB identity over a conflicting legacy display name', () => {
    const result = scoreDesignWithLlmPrior({
      targetName: 'PD-L1',
      pdbId: '5G51',
      metrics: { ipsae: 0.7 },
    });

    expect(result.targetKey).toBe('5G51');
  });

  it('resolves the canonical PD-L1 PDB without a saved target name', () => {
    const result = scoreDesignWithLlmPrior({
      pdbId: '5O45',
      metrics: { ipsae: 0.7 },
    });

    expect(result.targetKey).toBe('PDL1');
  });

  it('uses an explicitly labeled observed-metric fallback for unknown targets', () => {
    const result = scoreDesignWithLlmPrior({
      targetName: 'Novel target',
      pdbId: '9ZZZ',
      metrics: { iptm: 0.8, pDockQ: 0.6 },
    });

    expect(result.priorSource).toBe('observed_metric_fallback');
    expect(result.targetKey).toBeNull();
    expect(result.score).not.toBeNull();
    expect(result.caveats.join(' ')).toMatch(/no target-specific/i);
  });

  it('returns insufficient_metrics instead of manufacturing a score', () => {
    const result = scoreDesignWithLlmPrior({
      targetName: 'MDM2',
      metrics: { unrelated: 1 },
    });

    expect(result.status).toBe('insufficient_metrics');
    expect(result.score).toBeNull();
    expect(result.coverage).toBe(0);
    expect(result.availableMetrics).toBe(0);
    expect(result.caveats.join(' ')).toMatch(/no wet-lab measurement/i);
  });

  it('orients negative prior weights so lower liability values score better', () => {
    const lowRisk = scoreDesignWithLlmPrior({
      targetName: 'MDM2',
      metrics: { aggregation_propensity: 0.1 },
    });
    const highRisk = scoreDesignWithLlmPrior({
      targetName: 'MDM2',
      metrics: { aggregation_propensity: 0.9 },
    });

    expect(lowRisk.score).toBeGreaterThan(highRisk.score ?? 0);
  });
});
