import { z } from 'zod';
import { normaliseDesignProvenance } from '@papercrane/types';
import {
  LLM_META_SCORER_VERSION,
  MetaScoreDetailSchema,
  scoreDesignWithLlmPrior,
} from '../scoring/llmMetaScorer.js';

export const CandidateRecommendationSchema = z.enum([
  'advance',
  'review',
  'hold',
  'insufficient_data',
]);

export const CandidateDecisionReportSchema = z.object({
  reportVersion: z.literal('candidate-decision-v1'),
  generatedAt: z.string().datetime(),
  job: z.object({
    id: z.string(),
    status: z.string(),
    tool: z.string(),
    toolVersion: z.string().nullable(),
    adapterVersion: z.string().nullable(),
    imageDigest: z.string().nullable(),
    targetName: z.string().nullable(),
    targetPdbId: z.string().nullable(),
    requestedDesigns: z.number().int().nonnegative(),
    completedDesigns: z.number().int().nonnegative(),
  }),
  methodology: z.object({
    scorerVersion: z.literal(LLM_META_SCORER_VERSION),
    evidenceType: z.literal('computational'),
    experimental: z.literal(true),
    rankingRule: z.string(),
  }),
  summary: z.object({
    candidatesEvaluated: z.number().int().nonnegative(),
    candidatesAvailable: z.number().int().nonnegative(),
    truncated: z.boolean(),
    advance: z.number().int().nonnegative(),
    review: z.number().int().nonnegative(),
    hold: z.number().int().nonnegative(),
    insufficientData: z.number().int().nonnegative(),
    nextStep: z.string(),
  }),
  candidates: z.array(
    z.object({
      decisionRank: z.number().int().positive(),
      designId: z.string(),
      seed: z.number().int().nonnegative(),
      existingRank: z.number().int().nullable(),
      provenance: z.string(),
      recommendation: CandidateRecommendationSchema,
      confidence: z.enum(['high', 'medium', 'low']),
      reason: z.string(),
      sequence: z.string().nullable(),
      length: z.number().int().positive().nullable(),
      metrics: z.record(z.string(), z.unknown()),
      metaScore: MetaScoreDetailSchema,
    }),
  ),
  caveats: z.array(z.string()),
});

export type CandidateDecisionReport = z.infer<typeof CandidateDecisionReportSchema>;

type ReportJob = {
  id: string;
  status: string;
  tool: string;
  toolVersion?: string | null;
  adapterVersion?: string | null;
  imageDigest?: string | null;
  params?: unknown;
  seedsRequested: number;
  seedsConsumed: number;
  target?: { name?: string | null; pdbId?: string | null } | null;
};

type ReportDesign = {
  id: string;
  seed: number;
  rank?: number | null;
  provenance?: string | null;
  metrics?: unknown;
};

export function buildCandidateDecisionReport(input: {
  job: ReportJob;
  designs: ReportDesign[];
  generatedAt?: Date;
}): CandidateDecisionReport {
  const target = scoringTarget(input.job);
  const scored = input.designs.map((design) => {
    const metrics =
      design.metrics && typeof design.metrics === 'object'
        ? (design.metrics as Record<string, unknown>)
        : {};
    const metaScore = scoreDesignWithLlmPrior({ metrics, ...target });
    return { design, metrics, metaScore };
  });

  scored.sort((a, b) => {
    const scoreDelta = (b.metaScore.score ?? -1) - (a.metaScore.score ?? -1);
    if (scoreDelta !== 0) return scoreDelta;
    const coverageDelta = b.metaScore.coverage - a.metaScore.coverage;
    if (coverageDelta !== 0) return coverageDelta;
    return a.design.seed - b.design.seed;
  });

  const candidates: CandidateDecisionReport['candidates'] = scored.map((item, index) => {
    const provenance = normaliseDesignProvenance(item.design.provenance);
    const recommendation = recommendationFor(item.metaScore, index, provenance);
    const confidence = confidenceFor(item.metaScore.coverage, item.metaScore.availableMetrics);
    const topSignals = item.metaScore.contributions.slice(0, 2).map((entry) => entry.label);
    const sequence =
      typeof item.metrics.sequence === 'string' && item.metrics.sequence.length > 0
        ? item.metrics.sequence
        : null;
    const metricLength =
      typeof item.metrics.length === 'number' &&
      Number.isInteger(item.metrics.length) &&
      item.metrics.length > 0
        ? item.metrics.length
        : null;
    const scoreText =
      item.metaScore.score === null ? 'no score' : `${Math.round(item.metaScore.score * 100)}/100`;
    const signalText = topSignals.length > 0 ? `; strongest signals: ${topSignals.join(', ')}` : '';
    const provenanceText =
      provenance === 'real' ? '' : `Non-real ${provenance} provenance forces a hold. `;
    return {
      decisionRank: index + 1,
      designId: item.design.id,
      seed: item.design.seed,
      existingRank: item.design.rank ?? null,
      provenance,
      recommendation,
      confidence,
      reason: `${provenanceText}Experimental meta-score ${scoreText} with ${Math.round(
        item.metaScore.coverage * 100,
      )}% metric coverage${signalText}.`,
      sequence,
      length: metricLength ?? sequence?.length ?? null,
      metrics: item.metrics,
      metaScore: item.metaScore,
    };
  });

  const count = (value: CandidateDecisionReport['candidates'][number]['recommendation']) =>
    candidates.filter((candidate) => candidate.recommendation === value).length;
  const candidatesAvailable = Math.max(input.job.seedsConsumed, candidates.length);
  const truncated = candidates.length < candidatesAvailable;

  return {
    reportVersion: 'candidate-decision-v1',
    generatedAt: (input.generatedAt ?? new Date()).toISOString(),
    job: {
      id: input.job.id,
      status: input.job.status,
      tool: input.job.tool,
      toolVersion: input.job.toolVersion ?? null,
      adapterVersion: input.job.adapterVersion ?? null,
      imageDigest: input.job.imageDigest ?? null,
      targetName: target.targetName,
      targetPdbId: target.pdbId,
      requestedDesigns: input.job.seedsRequested,
      completedDesigns: input.job.seedsConsumed,
    },
    methodology: {
      scorerVersion: LLM_META_SCORER_VERSION,
      evidenceType: 'computational',
      experimental: true,
      rankingRule:
        'Descending experimental LLM meta-score, then metric coverage, then seed. Advance requires real provenance, a target-specific prior, top-3 rank, score >= 0.65, coverage >= 0.35, and at least two observed metrics.',
    },
    summary: {
      candidatesEvaluated: candidates.length,
      candidatesAvailable,
      truncated,
      advance: count('advance'),
      review: count('review'),
      hold: count('hold'),
      insufficientData: count('insufficient_data'),
      nextStep:
        candidates.length === 0
          ? 'Wait for at least one persisted design before making a candidate decision.'
          : truncated
            ? `This report covers ${candidates.length}/${candidatesAvailable} persisted candidates; increase the report limit or export the complete campaign before final selection.`
            : count('advance') > 0
              ? 'Manually inspect the advance set, run orthogonal computational checks, then select a small wet-lab panel.'
              : 'Collect missing metrics or run orthogonal validation before selecting a wet-lab panel.',
    },
    candidates,
    caveats: [
      'This report uses computational evidence only; it does not establish binding, specificity, expression, stability, or safety.',
      'The LLM prior is cached and versioned. It does not call an external model at report time.',
      'Recommendations are triage labels for human review, not autonomous experimental decisions.',
      'Synthetic or stub provenance must not be presented as a real model result.',
      ...(truncated
        ? [`Candidate output was truncated to ${candidates.length}/${candidatesAvailable} designs.`]
        : []),
    ],
  };
}

function recommendationFor(
  score: ReturnType<typeof scoreDesignWithLlmPrior>,
  zeroBasedRank: number,
  provenance: string,
): z.infer<typeof CandidateRecommendationSchema> {
  if (score.score === null || score.availableMetrics === 0) return 'insufficient_data';
  if (provenance !== 'real') return 'hold';
  if (
    zeroBasedRank < 3 &&
    score.priorSource === 'target_prior' &&
    score.score >= 0.65 &&
    score.coverage >= 0.35 &&
    score.availableMetrics >= 2
  ) {
    return 'advance';
  }
  if (score.score >= 0.5 && score.coverage >= 0.2) return 'review';
  return 'hold';
}

function confidenceFor(
  coverage: number,
  availableMetrics: number,
): 'high' | 'medium' | 'low' {
  if (coverage >= 0.75 && availableMetrics >= 3) return 'high';
  if (coverage >= 0.4 && availableMetrics >= 2) return 'medium';
  return 'low';
}

function scoringTarget(job: ReportJob): { targetName: string | null; pdbId: string | null } {
  const params =
    job.params && typeof job.params === 'object'
      ? (job.params as Record<string, unknown>)
      : null;
  const requestPdb = typeof params?.targetPdb === 'string' ? params.targetPdb.trim() : '';
  return {
    targetName: job.target?.name ?? null,
    pdbId:
      job.target?.pdbId ??
      (/^[A-Za-z0-9]{4}$/.test(requestPdb) ? requestPdb.toUpperCase() : null),
  };
}
