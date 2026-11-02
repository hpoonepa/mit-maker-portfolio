import { z } from 'zod';

export const LLM_META_SCORER_VERSION = 'llm-prior-v2-platform.1';

const ContributionSchema = z.object({
  metric: z.string(),
  label: z.string(),
  value: z.number(),
  weight: z.number(),
  alignedValue: z.number().min(0).max(1),
  contribution: z.number(),
});

export const MetaScoreSummarySchema = z.object({
  version: z.literal(LLM_META_SCORER_VERSION),
  evidenceType: z.literal('computational'),
  status: z.enum(['scored', 'insufficient_metrics']),
  score: z.number().min(0).max(1).nullable(),
  coverage: z.number().min(0).max(1),
  priorSource: z.enum(['target_prior', 'observed_metric_fallback']),
  targetKey: z.string().nullable(),
  availableMetrics: z.number().int().nonnegative(),
  experimental: z.literal(true),
});

export const MetaScoreDetailSchema = MetaScoreSummarySchema.extend({
  rationale: z.string(),
  liabilities: z.array(z.string()),
  citations: z.array(z.string()),
  contributions: z.array(ContributionSchema),
  caveats: z.array(z.string()),
});

export type MetaScoreSummary = z.infer<typeof MetaScoreSummarySchema>;
export type MetaScoreDetail = z.infer<typeof MetaScoreDetailSchema>;

type PriorDefinition = {
  aliases: string[];
  weights: Record<string, number>;
  rationale: string;
  liabilities: string[];
  citations: string[];
};

const STRUCTURAL_PRIOR: Record<string, number> = {
  computational__actifptm: 0.3,
  computational__interface_residues: 0.25,
  computational__boltz2_min_ipsae: 0.22,
  computational__boltz2_iptm: 0.12,
  shape_complementarity: 0.05,
  computational__boltz2_lis: 0.03,
  bio__aggregation_propensity: -0.015,
  bio__immunogenicity_proxy: -0.015,
};

const PRIORS: Record<string, PriorDefinition> = {
  EGFR: {
    aliases: ['EGFR', 'EPIDERMAL GROWTH FACTOR RECEPTOR'],
    weights: STRUCTURAL_PRIOR,
    rationale:
      'The cached EGFR prior concentrates on interface confidence and contact extent for the relatively flat domain III surface.',
    liabilities: [
      'A binder that misses the ligand-binding face may bind without inhibiting signaling.',
      'Single-residue dependence can create vulnerability to ectodomain resistance mutations.',
    ],
    citations: ['PMID:15837620', 'PMID:12610629'],
  },
  FGFR2: {
    aliases: ['FGFR2', 'FIBROBLAST GROWTH FACTOR RECEPTOR 2'],
    weights: STRUCTURAL_PRIOR,
    rationale:
      'The cached FGFR2 prior favors interface-quality metrics for its sheet-flat extracellular domain.',
    liabilities: [
      'Poor complementarity and aggregation can dominate on the exposed extracellular interface.',
      'Binder geometry can create receptor-clustering and agonism risk.',
    ],
    citations: ['PMID:40014401', 'PMID:30809251'],
  },
  IL7R: {
    aliases: ['IL7R', 'IL7RA', 'IL-7R', 'IL-7R ALPHA', 'CD127', '3DI2', '3DI3'],
    weights: {
      ...STRUCTURAL_PRIOR,
      computational__boltz2_lis: 0.06,
      bio__topology_loop_frac: -0.02,
    },
    rationale:
      'The cached IL7R prior emphasizes credible interface formation on a flat, polar cytokine-receptor surface.',
    liabilities: [
      'Flexible extracellular regions can reduce binding reproducibility.',
      'Hydrophobic nonspecific binding is a concern on the polar receptor face.',
    ],
    citations: ['PMID:40686280', 'PMID:40925205'],
  },
  INSULINR: {
    aliases: ['INSULINR', 'INSULIN RECEPTOR', 'INSR'],
    weights: {
      ...STRUCTURAL_PRIOR,
      aromatic_fraction: 0.03,
      hydrophobic_fraction: -0.03,
    },
    rationale:
      'The cached insulin-receptor prior combines interface evidence with small developability adjustments.',
    liabilities: [
      'Large extracellular interfaces raise aggregation and nonspecific-binding risk.',
      'Binding geometry can produce unwanted receptor agonism.',
    ],
    citations: ['PMID:41086805', 'PMID:36739671'],
  },
  MDM2: {
    aliases: ['MDM2', '1YCR'],
    weights: {
      computational__actifptm: 0.3,
      computational__boltz2_min_ipsae: 0.25,
      computational__interface_residues: 0.2,
      computational__boltz2_iptm: 0.12,
      shape_complementarity: 0.05,
      aromatic_fraction: 0.04,
      bio__topology_helix_frac: 0.03,
      bio__aggregation_propensity: -0.01,
    },
    rationale:
      'The cached MDM2 prior adds helix and aromatic signals for the p53-binding hydrophobic cleft.',
    liabilities: [
      'Binders lacking the p53-like hydrophobic anchor triad may not occupy the cleft.',
      'Hydrophobic enrichment can improve cleft packing while worsening solubility.',
    ],
    citations: ['PMID:8875929', 'PMID:22650254'],
  },
  MZB1: {
    aliases: ['MZB1'],
    weights: {
      ...STRUCTURAL_PRIOR,
      bio__disulfide_potential: 0.04,
    },
    rationale:
      'The cached MZB1 prior retains interface evidence and a small disulfide-context signal.',
    liabilities: [
      'The cysteine-rich ER protein creates disulfide-scrambling and reduction-sensitivity risks.',
    ],
    citations: ['PMID:33453188', 'PMID:31127044'],
  },
  PD1: {
    aliases: ['PD1', 'PD-1', 'PDCD1'],
    weights: {
      ...STRUCTURAL_PRIOR,
      computational__interface_residues: 0.3,
      computational__actifptm: 0.25,
      computational__boltz2_min_ipsae: 0.2,
    },
    rationale:
      'The cached PD-1 prior places contact extent first for the IgV checkpoint interface.',
    liabilities: [
      'Flexible epitope presentation can produce variable binding modes.',
      'Therapeutic use makes immunogenicity and aggregation relevant secondary risks.',
    ],
    citations: ['PMID:20636820', 'PMID:39333505'],
  },
  PDGFRB: {
    aliases: ['PDGFRB', 'PDGFR-B', 'PLATELET DERIVED GROWTH FACTOR RECEPTOR B'],
    weights: STRUCTURAL_PRIOR,
    rationale:
      'The cached PDGFRB prior favors interface confidence on a flexible sheet-rich extracellular domain.',
    liabilities: [
      'Flexible extracellular loops can reduce the stability of predicted contacts.',
      'Receptor clustering creates a potential agonism failure mode.',
    ],
    citations: ['PMID:41519838', 'PMID:36788091'],
  },
  PDL1: {
    aliases: ['PDL1', 'PD-L1', 'CD274', '5O45'],
    weights: {
      ...STRUCTURAL_PRIOR,
      computational__actifptm: 0.3,
      computational__boltz2_min_ipsae: 0.25,
      computational__interface_residues: 0.2,
      computational__boltz2_iptm: 0.15,
      shape_complementarity: 0.08,
      bio__aggregation_propensity: -0.02,
    },
    rationale:
      'The cached PD-L1 prior emphasizes interface confidence and shape complementarity on its flat IgV face.',
    liabilities: [
      'The flat beta-sheet interface is difficult to engage with high specificity.',
      'Hydrophobic patches can create aggregation or off-target binding.',
    ],
    citations: ['PMID:34596400', 'PMID:32051224'],
  },
  PMVK: {
    aliases: ['PMVK', 'PHOSPHOMEVALONATE KINASE'],
    weights: STRUCTURAL_PRIOR,
    rationale:
      'The cached PMVK prior focuses on interface evidence around a charged, conformationally active cleft.',
    liabilities: [
      'Charge complementarity and lid-domain motion can limit binding at the active-site cleft.',
    ],
    citations: ['PMID:19485344', 'PMID:18618710'],
  },
  '5G51': {
    aliases: ['5G51', 'DWV VP3', 'DEFORMED WING VIRUS VP3'],
    weights: {
      computational__actifptm: 0.2641509433962264,
      computational__interface_residues: 0.24528301886792453,
      computational__boltz2_min_ipsae: 0.22641509433962262,
      shape_complementarity: 0.11320754716981131,
      bio__topology_loop_frac: -0.04716981132075472,
      bio__aggregation_propensity: -0.028301886792452827,
      aromatic_fraction: 0.07547169811320754,
    },
    rationale:
      'The cached 5G51 prior targets the DWV VP3 capsid surface and emphasizes interface evidence, contact extent, and shape complementarity.',
    liabilities: [
      'High loop content can require conformational selection or induced fit.',
      'Aromatic packing may help the capsid interface but can reduce solubility.',
    ],
    citations: ['PMID:30857192', 'PMID:37845211'],
  },
};

const FALLBACK_WEIGHTS: Record<string, number> = {
  computational__boltz2_min_ipsae: 0.6,
  computational__boltz2_iptm: 0.25,
  pdockq: 0.15,
};

const METRICS: Record<
  string,
  { aliases: string[]; label: string; normalize: (value: number) => number }
> = {
  computational__actifptm: {
    aliases: ['actifptm', 'actif_ptm'],
    label: 'actiF-pTM',
    normalize: unit,
  },
  computational__interface_residues: {
    aliases: ['interface_residues', 'interfaceResidues', 'n_interface_residues'],
    label: 'interface residues',
    normalize: (value) => unit(value / 30),
  },
  computational__boltz2_min_ipsae: {
    aliases: ['min_ipsae', 'ipsae', 'ipSAE', 'best_ipsae'],
    label: 'min ipSAE',
    normalize: unit,
  },
  computational__boltz2_iptm: {
    aliases: ['iptm', 'ipTM'],
    label: 'ipTM',
    normalize: unit,
  },
  computational__boltz2_lis: {
    aliases: ['lis', 'LIS'],
    label: 'LIS',
    normalize: unit,
  },
  computational__boltz2_complex_iplddt: {
    aliases: ['complex_iplddt', 'complexIpLddt', 'iplddt'],
    label: 'complex ipLDDT',
    normalize: percentOrUnit,
  },
  shape_complementarity: {
    aliases: ['shape_complementarity', 'interfaceSC', 'interface_sc'],
    label: 'shape complementarity',
    normalize: unit,
  },
  pdockq: {
    aliases: ['pdockq', 'pDockQ', 'dockq'],
    label: 'pDockQ',
    normalize: unit,
  },
  aromatic_fraction: {
    aliases: ['aromatic_fraction'],
    label: 'aromatic fraction',
    normalize: unit,
  },
  hydrophobic_fraction: {
    aliases: ['hydrophobic_fraction'],
    label: 'hydrophobic fraction',
    normalize: unit,
  },
  bio__aggregation_propensity: {
    aliases: ['bio__aggregation_propensity', 'aggregation_propensity'],
    label: 'aggregation propensity',
    normalize: unit,
  },
  bio__immunogenicity_proxy: {
    aliases: ['bio__immunogenicity_proxy', 'immunogenicity_proxy'],
    label: 'immunogenicity proxy',
    normalize: unit,
  },
  bio__disulfide_potential: {
    aliases: ['bio__disulfide_potential', 'disulfide_potential'],
    label: 'disulfide potential',
    normalize: unit,
  },
  bio__topology_helix_frac: {
    aliases: ['bio__topology_helix_frac', 'topology_helix_frac'],
    label: 'helix fraction',
    normalize: unit,
  },
  bio__topology_loop_frac: {
    aliases: ['bio__topology_loop_frac', 'topology_loop_frac'],
    label: 'loop fraction',
    normalize: unit,
  },
};

const BASE_CAVEATS = [
  'Computed exclusively from stored in-silico metrics; no wet-lab measurement or validation is used.',
  'Experimental ranking aid, not a probability of binding.',
  'The corrected benchmark is underpowered at 11 targets and shows no statistically resolved lift over existing baselines.',
  'Only metrics present on this design contribute; coverage reports the fraction of prior weight observed.',
];

export function scoreDesignWithLlmPrior(input: {
  metrics: Record<string, unknown>;
  targetName?: string | null;
  pdbId?: string | null;
}): MetaScoreDetail {
  const resolved = resolvePrior(input.targetName, input.pdbId);
  const weights = resolved?.prior.weights ?? FALLBACK_WEIGHTS;
  const totalWeight = sumAbs(weights);
  const contributions: MetaScoreDetail['contributions'] = [];
  let observedWeight = 0;
  let weightedEvidence = 0;

  for (const [metric, weight] of Object.entries(weights)) {
    const definition = METRICS[metric];
    if (!definition) continue;
    const value = metricValue(input.metrics, [metric, ...definition.aliases]);
    if (value === null) continue;
    const normalized = definition.normalize(value);
    const alignedValue = weight >= 0 ? normalized : 1 - normalized;
    const contribution = Math.abs(weight) * alignedValue;
    observedWeight += Math.abs(weight);
    weightedEvidence += contribution;
    contributions.push({
      metric,
      label: definition.label,
      value,
      weight,
      alignedValue,
      contribution,
    });
  }

  contributions.sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight));
  const coverage = totalWeight === 0 ? 0 : unit(observedWeight / totalWeight);
  const status = observedWeight > 0 ? 'scored' : 'insufficient_metrics';

  return {
    version: LLM_META_SCORER_VERSION,
    evidenceType: 'computational',
    status,
    score: status === 'scored' ? unit(weightedEvidence / observedWeight) : null,
    coverage,
    priorSource: resolved ? 'target_prior' : 'observed_metric_fallback',
    targetKey: resolved?.key ?? null,
    availableMetrics: contributions.length,
    experimental: true,
    rationale:
      resolved?.prior.rationale ??
      'No cached target-specific LLM prior matched this target. The fallback uses observed interface metrics only.',
    liabilities: resolved?.prior.liabilities ?? [],
    citations: resolved?.prior.citations ?? [],
    contributions,
    caveats: [
      ...BASE_CAVEATS,
      ...(resolved
        ? []
        : ['No target-specific biological prior was applied; this is the observed-metric fallback.']),
    ],
  };
}

export function metaScoreSummary(detail: MetaScoreDetail): MetaScoreSummary {
  return {
    version: detail.version,
    evidenceType: detail.evidenceType,
    status: detail.status,
    score: detail.score,
    coverage: detail.coverage,
    priorSource: detail.priorSource,
    targetKey: detail.targetKey,
    availableMetrics: detail.availableMetrics,
    experimental: true,
  };
}

function resolvePrior(
  targetName?: string | null,
  pdbId?: string | null,
): { key: string; prior: PriorDefinition } | null {
  // Exact PDB identity wins over a conflicting display name. This matters for
  // historical fixtures that incorrectly called the DWV VP3 structure 5G51
  // "PD-L1"; silently selecting the PD-L1 prior would be scientifically wrong.
  for (const candidate of [pdbId, targetName]) {
    if (!candidate) continue;
    const normalized = normalizeIdentity(candidate);
    for (const [key, prior] of Object.entries(PRIORS)) {
      const aliases = [key, ...prior.aliases].map(normalizeIdentity);
      if (aliases.includes(normalized)) return { key, prior };
    }
  }
  return null;
}

function metricValue(metrics: Record<string, unknown>, aliases: string[]): number | null {
  for (const alias of aliases) {
    const direct = finiteNumber(metrics[alias]);
    if (direct !== null) return direct;
    const lower = alias.toLowerCase();
    for (const [key, raw] of Object.entries(metrics)) {
      if (key.toLowerCase() !== lower) continue;
      const value = finiteNumber(raw);
      if (value !== null) return value;
    }
  }
  return null;
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function normalizeIdentity(value: string): string {
  return value.toUpperCase().replace(/[^A-Z0-9]/g, '');
}

function sumAbs(weights: Record<string, number>): number {
  return Object.values(weights).reduce((sum, value) => sum + Math.abs(value), 0);
}

function unit(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function percentOrUnit(value: number): number {
  return unit(value > 1 ? value / 100 : value);
}
