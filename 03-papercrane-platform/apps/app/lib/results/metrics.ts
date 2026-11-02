import { PUBLIC_TOOL_CATALOG } from "../../../web/lib/tool-catalog";

export type ResultMetric = {
  key: string;
  label: string;
  value: number;
  description?: string;
  direction?: "low" | "high";
  percent?: boolean;
};

type Definition = Omit<ResultMetric, "key" | "value"> & { aliases: string[] };
const MPNN: Definition[] = [
  { aliases: ["score"], label: "Sequence score", direction: "low", description: "Mean negative log-likelihood at designed positions. Lower values indicate a sequence the model considers more compatible with the input backbone." },
  { aliases: ["global_score"], label: "Global score", direction: "low", description: "Mean negative log-likelihood across all scored residues, including fixed positions." },
  { aliases: ["recovery", "seq_recovery", "sequence_recovery"], label: "Sequence recovery", percent: true, description: "Fraction of designed positions matching the input sequence. This measures similarity, not experimental success." },
  { aliases: ["sample_perplexity"], label: "Perplexity", direction: "low", description: "Exponential of the sequence score. Lower values indicate greater model likelihood." },
];
const BOLTZ: Definition[] = [
  { aliases: ["complex_plddt"], label: "pLDDT (0–1)", direction: "high", description: "Mean local structural confidence across the prediction, on Boltz’s native 0–1 scale." },
  { aliases: ["pTM", "ptm"], label: "pTM", direction: "high", description: "Predicted TM score for the overall structure, from 0 to 1." },
  { aliases: ["confidence_score"], label: "Model confidence (0–1)", direction: "high", description: "Boltz’s aggregate: 0.8 × mean pLDDT + 0.2 × ipTM (pTM for a single chain)." },
  { aliases: ["complex_pde"], label: "PDE (Å)", direction: "low", description: "Mean predicted distance error in angstroms." },
  { aliases: ["ipTM", "iptm", "computational__boltz2_iptm"], label: "ipTM", direction: "high", description: "Predicted TM score across chain interfaces, from 0 to 1." },
  { aliases: ["protein_iptm"], label: "Protein interface ipTM", direction: "high", description: "ipTM over protein–protein interfaces." },
  { aliases: ["ligand_iptm"], label: "Ligand interface ipTM", direction: "high", description: "ipTM over protein–ligand interfaces." },
  { aliases: ["complex_iplddt"], label: "Interface pLDDT (0–1)", direction: "high", description: "Mean pLDDT with greater weight on interface tokens." },
  { aliases: ["complex_ipde"], label: "Interface PDE (Å)", direction: "low", description: "Mean predicted distance error across interfaces, in angstroms." },
];
const INTERFACE_METRICS = new Set(["iptm", "computational__boltz2_iptm", "protein_iptm", "ligand_iptm", "complex_iplddt", "complex_ipde", "ipsae", "computational__boltz2_min_ipsae", "dockq", "pdockq", "ipae_mean"]);
const COMMON: Definition[] = [
  { aliases: ["ipSAE", "ipsae", "computational__boltz2_min_ipsae"], label: "ipSAE" },
  { aliases: ["ipTM", "iptm", "computational__boltz2_iptm"], label: "ipTM" },
  { aliases: ["pTM", "ptm"], label: "pTM" },
  { aliases: ["pLDDT", "plddt", "plddt_mean", "mean_plddt"], label: "pLDDT" },
  { aliases: ["pAE", "pae", "pae_mean"], label: "PAE" },
  { aliases: ["DockQ", "dockq"], label: "DockQ" },
  { aliases: ["pDockQ", "pdockq"], label: "pDockQ" },
];
const EXCLUDED = new Set(["sequence", "length", "seed", "rank", "composite_rank", "composite", "meta_score", "metascore", "temperature", "chain_count"]);

export function finalTool(tool?: string | null): string {
  return (tool ?? "").split("+").at(-1)?.trim().toLowerCase() ?? "";
}
export function toolLabel(tool?: string | null): string {
  if (!tool) return "Result";
  return tool.split("+").map((id) => PUBLIC_TOOL_CATALOG.find((t) => t.slug === id.trim())?.name ?? id.trim()).join(" → ");
}
export function isBoltz(tool?: string | null): boolean {
  return ["boltz1", "boltz2"].includes(finalTool(tool));
}
export function isMpnn(tool?: string | null): boolean {
  return ["proteinmpnn", "solublempnn"].includes(finalTool(tool));
}
/** Sequence and analysis tools often write a CIF container without atom coordinates. */
export function expectsCoordinates(tool?: string | null): boolean {
  const entry = PUBLIC_TOOL_CATALOG.find((t) => t.slug === finalTool(tool));
  return !!entry && ["structure_prediction", "binder_design", "backbone_generation"].includes(entry.category);
}

export function resultMetrics(tool: string | null | undefined, metrics: Record<string, unknown>): ResultMetric[] {
  const definitions = isMpnn(tool) ? [...MPNN, ...COMMON] : isBoltz(tool) ? [...BOLTZ, ...COMMON] : COMMON;
  const hideInterface = isBoltz(tool) && metrics.chain_count === 1;
  const excluded = (key: string) => EXCLUDED.has(key.toLowerCase()) || (hideInterface && INTERFACE_METRICS.has(key.toLowerCase()));
  const used = new Set<string>();
  const result: ResultMetric[] = [];
  for (const def of definitions) {
    const key = def.aliases.find((alias) => !used.has(alias) && !excluded(alias) && typeof metrics[alias] === "number" && Number.isFinite(metrics[alias]));
    for (const alias of def.aliases) used.add(alias);
    if (key) {
      const { aliases: _, ...meta } = def;
      result.push({ ...meta, key, value: metrics[key] as number });
    }
  }
  for (const [key, value] of Object.entries(metrics)) {
    if (used.has(key) || excluded(key) || typeof value !== "number" || !Number.isFinite(value)) continue;
    result.push({ key, value, label: key.replace(/_/g, " ") });
  }
  return result;
}
export function formatResultMetric(metric: ResultMetric): string {
  if (metric.percent) return `${(metric.value * 100).toFixed(2)}%`;
  if (Number.isInteger(metric.value)) return String(metric.value);
  if (Math.abs(metric.value) > 0 && Math.abs(metric.value) < 0.0001) return metric.value.toExponential(3);
  return metric.value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}
