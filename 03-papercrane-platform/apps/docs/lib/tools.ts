// Static tool catalog data. Mirrors /tools/*/manifest.json so we can render
// without crossing the workspace boundary at request time.
export type ToolEntry = {
  id: string;
  name: string;
  blurb: string;
  category: string;
  tier: "open" | "frontier";
  gpu: string;
  estSeconds: number;
  whenToUse: string;
  notes?: string;
};

export const TOOLS: ToolEntry[] = [
  {
    id: "rfdiffusion",
    name: "RFdiffusion",
    blurb: "Diffusion-based de novo backbone generation.",
    category: "backbone_generation",
    tier: "open",
    gpu: "A100-40GB",
    estSeconds: 35,
    whenToUse:
      "Designing fresh binder scaffolds against a target with no prior art. Pair with ProteinMPNN for sequences and AF2/Boltz-2 for validation.",
  },
  {
    id: "chroma",
    name: "Chroma",
    blurb: "Generative model for backbones with programmable constraints.",
    category: "backbone_generation",
    tier: "open",
    gpu: "A100-40GB",
    estSeconds: 50,
    whenToUse: "When you need symmetric oligomers or motif scaffolding with constraints RFdiffusion does not expose.",
  },
  {
    id: "proteinmpnn",
    name: "ProteinMPNN",
    blurb: "Inverse folding — assigns sequence to a backbone.",
    category: "sequence_design",
    tier: "open",
    gpu: "A10",
    estSeconds: 4,
    whenToUse: "Standard pairing after RFdiffusion. Cheap, fast, and reliable.",
  },
  {
    id: "ligandmpnn",
    name: "LigandMPNN",
    blurb: "Sequence design conditioned on bound ligands.",
    category: "sequence_design",
    tier: "open",
    gpu: "A10",
    estSeconds: 6,
    whenToUse: "Active site design, cofactor binding, or any pocket where the small molecule must stay coordinated.",
  },
  {
    id: "solublempnn",
    name: "SolubleMPNN",
    blurb: "Sequence design tuned for E. coli expression.",
    category: "sequence_design",
    tier: "open",
    gpu: "A10",
    estSeconds: 5,
    whenToUse: "When yield matters more than affinity — early hit-finding before assays.",
  },
  {
    id: "bindcraft",
    name: "BindCraft",
    blurb: "End-to-end binder design with AF2 validation in the loop.",
    category: "binder_design",
    tier: "open",
    gpu: "A100-40GB",
    estSeconds: 140,
    whenToUse: "Highest experimental success rate when you want a complete pipeline rather than discrete steps.",
  },
  {
    id: "boltzgen",
    name: "BoltzGen",
    blurb: "All-atom diffusion with side-chain awareness from the start.",
    category: "binder_design",
    tier: "open",
    gpu: "A100-40GB",
    estSeconds: 90,
    whenToUse: "Designing around small molecules or precise interface geometries.",
  },
  {
    id: "boltz1",
    name: "Boltz-1",
    blurb: "Open-source structure predictor (single-pass).",
    category: "structure_prediction",
    tier: "open",
    gpu: "A100-40GB",
    estSeconds: 70,
    whenToUse: "Cheap validation pass for sequence sweeps before paying for Boltz-2 or AF3.",
  },
  {
    id: "boltz2",
    name: "Boltz-2",
    blurb: "Higher-accuracy open-source predictor with affinity head.",
    category: "structure_prediction",
    tier: "open",
    gpu: "A100-80GB",
    estSeconds: 110,
    whenToUse: "Default validation for binder hits. Reports ipTM, pAE, and affinity scores.",
  },
  {
    id: "chai1",
    name: "Chai-1",
    blurb: "Frontier predictor with multi-chain and ligand support.",
    category: "structure_prediction",
    tier: "frontier",
    gpu: "A100-80GB",
    estSeconds: 130,
    whenToUse: "When AF3 is unavailable but you need frontier-grade accuracy on complexes.",
  },
  {
    id: "alphafold3",
    name: "AlphaFold 3",
    blurb: "Frontier multi-modal predictor, gold-standard validation.",
    category: "structure_prediction",
    tier: "frontier",
    gpu: "H100-80GB",
    estSeconds: 180,
    whenToUse: "Final validation gate before ordering. Use sparingly — most expensive node in the graph.",
    notes: "Frontier tier — counts double against your seed allowance.",
  },
  {
    id: "esm2",
    name: "ESM-2",
    blurb: "Protein language model for embeddings and PLL scoring.",
    category: "embedding_scoring",
    tier: "open",
    gpu: "A10",
    estSeconds: 1,
    whenToUse: "Cheap pre-filter — drop sequences with low pseudo-log-likelihood before paying for structure.",
  },
];

export function toolBySlug(slug: string): ToolEntry | undefined {
  return TOOLS.find((t) => t.id === slug);
}

export const TOOL_SLUGS = TOOLS.map((t) => t.id);
