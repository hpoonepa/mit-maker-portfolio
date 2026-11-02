import { describe, expect, it } from 'vitest';
import { buildCandidateDecisionReport } from '../src/reporting/candidateDecisionReport.js';

const JOB = {
  id: 'job-1',
  status: 'succeeded',
  tool: 'bindcraft',
  toolVersion: '1.0.0',
  adapterVersion: 'adapter-1',
  imageDigest: 'sha256:abc',
  seedsRequested: 3,
  seedsConsumed: 3,
  target: { name: 'EGFR', pdbId: null },
};

describe('candidate decision report', () => {
  it.each([undefined, null, '', 'unrecognized'])('does not advance a candidate with unverified origin %s', (provenance) => {
    const report = buildCandidateDecisionReport({
      job: JOB,
      designs: [{ id: 'unknown', seed: 1, provenance, metrics: {
        computational__actifptm: 0.99,
        computational__interface_residues: 30,
        computational__boltz2_min_ipsae: 0.99,
      } }],
    });
    expect(report.candidates[0]).toMatchObject({ provenance: 'unknown', recommendation: 'hold' });
    expect(report.summary.advance).toBe(0);
  });
  it('ranks candidates with the versioned meta scorer and recommends a supported top hit', () => {
    const report = buildCandidateDecisionReport({
      job: JOB,
      generatedAt: new Date('2026-07-21T12:00:00.000Z'),
      designs: [
        {
          id: 'design-low',
          seed: 2,
          metrics: {
            computational__actifptm: 0.45,
            computational__interface_residues: 8,
            computational__boltz2_min_ipsae: 0.4,
          },
        },
        {
          id: 'design-high',
          provenance: 'real',
          seed: 1,
          metrics: {
            computational__actifptm: 0.92,
            computational__interface_residues: 24,
            computational__boltz2_min_ipsae: 0.86,
          },
        },
      ],
    });

    expect(report.generatedAt).toBe('2026-07-21T12:00:00.000Z');
    expect(report.methodology.experimental).toBe(true);
    expect(report.candidates[0]).toMatchObject({
      designId: 'design-high',
      decisionRank: 1,
      recommendation: 'advance',
    });
    expect(report.candidates[0]?.metaScore.version).toBe(report.methodology.scorerVersion);
    expect(report.summary.advance).toBe(1);
    expect(report.caveats.join(' ')).toMatch(/computational evidence only/i);
  });

  it('does not manufacture a recommendation when required metrics are absent', () => {
    const report = buildCandidateDecisionReport({
      job: JOB,
      designs: [{ id: 'design-empty', seed: 1, metrics: { unrelated: 1 } }],
    });

    expect(report.candidates[0]).toMatchObject({
      recommendation: 'insufficient_data',
      confidence: 'low',
    });
    expect(report.candidates[0]?.metaScore.score).toBeNull();
    expect(report.summary.insufficientData).toBe(1);
  });

  it('never advances synthetic or stub candidates', () => {
    const report = buildCandidateDecisionReport({
      job: JOB,
      designs: [
        {
          id: 'design-stub',
          seed: 1,
          provenance: 'stub',
          metrics: {
            computational__actifptm: 0.99,
            computational__interface_residues: 30,
            computational__boltz2_min_ipsae: 0.99,
          },
        },
      ],
    });

    expect(report.candidates[0]).toMatchObject({ provenance: 'stub', recommendation: 'hold' });
    expect(report.summary.advance).toBe(0);
  });
});
