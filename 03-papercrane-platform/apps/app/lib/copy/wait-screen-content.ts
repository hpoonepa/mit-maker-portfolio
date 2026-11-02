/**
 * Static copy for the JobWaitScreen. Lives outside the component so
 * non-engineers (Vedant or Harsha) can edit voice/messaging without
 * touching React. Keep voice = scrappy founder, technically grounded,
 * no corporate-speak. The reference voice is `apps/web/components/sections/About.tsx`.
 *
 * Constraints:
 *   - Sentences SHORT. The user is staring at this for minutes.
 *   - First person plural ("we"): we want them to know two humans built this.
 *   - No emojis. No "AI-powered". No "leverage". No "synergy".
 */

export const FOUNDER_STORY: readonly string[] = [
  "We're Harsha and Vedant: two high-schoolers who lost three weekends to Conda before our first design ever folded.",
  "Paper Crane is the tool we wished existed: ten state-of-the-art protein design models, one URL, no CUDA tears.",
  "You're using a private beta. Things will be rough. Tell us what hurts and we'll fix it that night.",
] as const;

export const HONEST_NOTE = {
  body: "We're on slower GPUs while we wait on Modal credits. Thanks for your patience while we get this running.",
  signoff: "Harsha & Vedant",
} as const;

export interface ToolEducation {
  tagline: string;
  what: string;
}

/**
 * Per-tool "while you wait, here's what's happening" copy.
 * Keys MUST match the canonical tool slug used in `job.toolId` and
 * the catalogue rows in the `tools` Postgres table. Composite pipeline
 * ids (e.g. "rfdiffusion+proteinmpnn+boltz2") fall back to the first
 * segment.
 *
 * If a tool isn't listed here the wait screen renders the FALLBACK_EDUCATION
 * entry rather than crashing: keeps the screen forward-compatible with
 * new tools the catalogue adds before this copy file is updated.
 */
export const TOOL_EDUCATION: Record<string, ToolEducation> = {
  bindcraft: {
    tagline: "End-to-end binder hallucination with AF2 validation",
    what: "BindCraft jointly designs a backbone and a sequence by running AlphaFold2 in a tight loss-driven loop. Each seed is essentially asking AF2 'what protein, if it existed, would dock onto this target?' and then hill-climbing until the answer is convincing.",
  },
  rfdiffusion: {
    tagline: "Diffusion-based de novo backbone generation",
    what: "RFdiffusion runs a diffusion process on protein coordinates to denoise random noise into a plausible backbone shape. We pin your hotspots and let it sculpt around them: the sequence comes later from ProteinMPNN.",
  },
  proteinmpnn: {
    tagline: "Inverse folding: backbone in, sequence out",
    what: "Given a 3D backbone, ProteinMPNN predicts the amino-acid sequence most likely to fold into it. It's faster than designing from scratch and it's the workhorse step after RFdiffusion generates shape.",
  },
  solublempnn: {
    tagline: "ProteinMPNN tuned for soluble expression",
    what: "Same architecture as ProteinMPNN, but trained to avoid sequences that ball up into inclusion bodies in E. coli. Use this when the design has to actually express in a real lab.",
  },
  ligandmpnn: {
    tagline: "Sequence design around small molecules",
    what: "An MPNN variant that sees the ligand atoms during design, so the residues lining your pocket get picked with the small molecule in mind. Critical for enzyme active sites and metal binding.",
  },
  boltz1: {
    tagline: "Open-source structure prediction",
    what: "Boltz-1 predicts the folded structure of your designed sequence against the target. We use it to validate that the binder actually docks the way the designer intended: confidence metrics (ipTM, pLDDT) come out of this step.",
  },
  boltz2: {
    tagline: "Boltz-2: next-gen complex prediction",
    what: "The successor to Boltz-1, better at protein-ligand complexes and faster on multi-chain assemblies. We default to this for validation when the GPU has the headroom.",
  },
  boltzgen: {
    tagline: "All-atom diffusion design with ligands",
    what: "BoltzGen diffuses in all-atom space (side chains included), so it can design around small molecules and precise binding geometries from the first step instead of starting with only the backbone.",
  },
  alphafold3: {
    tagline: "AlphaFold 3: multi-modal complex prediction",
    what: "AF3 predicts protein, ligand, nucleic-acid, and small-molecule complexes in a single forward pass. We use it as a stricter validator when you need the highest-confidence structure call.",
  },
  chai1: {
    tagline: "Chai-1: foundation structure prediction",
    what: "Chai-1 is a foundation model for biomolecular structure. We use it as an alternative validator to AlphaFold: running both and comparing is a common sanity check for high-stakes designs.",
  },
  chroma: {
    tagline: "Programmable protein generation",
    what: "Chroma is a generative model that lets you condition on shape, symmetry, or substructure constraints. Good for symmetric oligomers and proteins-with-rules tasks where RFdiffusion alone is too unconstrained.",
  },
  esm2: {
    tagline: "ESM-2: protein language model",
    what: "ESM-2 scores how 'plausible' a sequence looks based on millions of natural proteins. We use it to filter designs before structure prediction: bad PLL means probably bad fold.",
  },
};

export const FALLBACK_EDUCATION: ToolEducation = {
  tagline: "Running on Paper Crane infrastructure",
  what: "Your job is processing on a GPU we've provisioned for this tool. Each seed runs a separate trajectory; when they're all done we collect outputs, score them, and surface the top hits.",
};

export interface ComingNextItem {
  title: string;
  detail?: string;
}

export const COMING_NEXT: readonly ComingNextItem[] = [
  {
    title: "Dynamics-aware design for cryptic pockets",
    detail: "BioEmu-style ensembles so you can target pockets that only open in solution.",
  },
  {
    title: "One-click structure-to-binder preset",
    detail: "Drop in a PDB, pick a chain, get back ranked binders. No pipeline composition needed.",
  },
  {
    title: "Public leaderboard for community targets",
    detail: "Submit a target, watch designers from around the world try to crack it.",
  },
] as const;

/**
 * Resolve a tool slug (possibly composite like "rfdiffusion+proteinmpnn+boltz2")
 * to its education entry. Returns the entry for the FIRST recognised tool in
 * the chain: the user is primarily watching that step initialise.
 */
export function resolveToolEducation(toolId: string): ToolEducation {
  const segments = toolId.split("+").map((s) => s.trim().toLowerCase());
  for (const segment of segments) {
    const hit = TOOL_EDUCATION[segment];
    if (hit) return hit;
  }
  return FALLBACK_EDUCATION;
}

/**
 * Human display name for the tool chain. We prefer "BindCraft" over
 * "bindcraft" and join multi-tool chains with a thin arrow.
 */
export function formatToolDisplayName(toolId: string): string {
  const PRETTY: Record<string, string> = {
    bindcraft: "BindCraft",
    rfdiffusion: "RFdiffusion",
    proteinmpnn: "ProteinMPNN",
    solublempnn: "SolubleMPNN",
    ligandmpnn: "LigandMPNN",
    boltz1: "Boltz-1",
    boltz2: "Boltz-2",
    boltzgen: "BoltzGen",
    alphafold3: "AlphaFold 3",
    chai1: "Chai-1",
    chroma: "Chroma",
    esm2: "ESM-2",
  };
  const segments = toolId.split("+").map((s) => s.trim());
  return segments
    .map((s) => PRETTY[s.toLowerCase()] ?? s)
    .join(" → ");
}
