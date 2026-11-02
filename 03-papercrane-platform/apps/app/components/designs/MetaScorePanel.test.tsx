import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MetaScorePanel, type ExperimentalMetaScore } from './MetaScorePanel';

const SCORE: ExperimentalMetaScore = {
  version: 'llm-prior-v2-platform.1',
  evidenceType: 'computational',
  status: 'scored',
  score: 0.82,
  coverage: 0.6,
  priorSource: 'target_prior',
  targetKey: '5G51',
  availableMetrics: 3,
  experimental: true,
  rationale: 'Cached target-specific rationale.',
  liabilities: ['Loop flexibility can reduce specificity.'],
  citations: ['PMID:30857192'],
  contributions: [
    {
      metric: 'computational__boltz2_min_ipsae',
      label: 'min ipSAE',
      value: 0.82,
      weight: 0.23,
      alignedValue: 0.82,
      contribution: 0.1886,
    },
  ],
  caveats: [],
};

describe('MetaScorePanel', () => {
  it('renders score provenance, coverage, drivers, and the scientific caveat', () => {
    render(<MetaScorePanel score={SCORE} />);

    expect(screen.getByRole('heading', { name: /llm meta-score/i })).toBeTruthy();
    expect(screen.getByText(/experimental · computational only · 5g51 prior/i)).toBeTruthy();
    expect(screen.getAllByText('82')).toHaveLength(2);
    expect(screen.getByText(/60% · 3 metrics/i)).toBeTruthy();
    expect(screen.getByText(/min ipsae/i)).toBeTruthy();
    expect(screen.getByText(/no wet-lab measurement/i)).toBeTruthy();
    expect(screen.getByText(/not p\(bind\)/i)).toBeTruthy();
    expect(screen.getByText(/statistically unresolved/i)).toBeTruthy();
  });

  it('labels the fallback rather than implying a target-specific prior', () => {
    render(
      <MetaScorePanel
        score={{
          ...SCORE,
          priorSource: 'observed_metric_fallback',
          targetKey: null,
          liabilities: [],
          citations: [],
        }}
      />,
    );

    expect(
      screen.getByText(/experimental · computational only · metric fallback/i),
    ).toBeTruthy();
  });
});
