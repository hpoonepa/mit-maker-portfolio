/**
 * Static, plain-English "what each tool is good at" lines, keyed by tool slug.
 *
 * Honest, non-hyped one-liners describing the real strength of each tool so
 * users can pick sensibly in the job wizard. Keep each line ~8-14 words.
 */
export const TOOL_GOOD_AT: Record<string, string> = {
  bindcraft:
    "End-to-end binder design with built-in AF2 filtering; solid experimental hit rates.",
  rfdiffusion:
    "Generates de novo backbones and binder scaffolds; needs sequence design afterward.",
  proteinmpnn:
    "Designs sequences for a fixed backbone via fast, reliable inverse folding.",
  ligandmpnn:
    "Sequence design aware of small molecules, metals, and cofactors near the pocket.",
  solublempnn:
    "Sequence design biased toward solubility and better expression in E. coli.",
  boltz2:
    "Open structure and affinity prediction for complexes; good for validating binders.",
  chai1:
    "Predicts protein, complex, and ligand structures; an open AlphaFold3 alternative.",
  boltzgen:
    "All-atom generative binder design with side-chain awareness around ligands.",
  esm2: "Protein language model for embeddings and scoring sequence plausibility, no MSA.",
  alphafold3:
    "High-accuracy structure prediction for proteins, complexes, nucleic acids, and ligands.",
  chroma:
    "Generative backbone model for novel proteins with programmable shape constraints.",
  rfdiffusionaa:
    "Ligand- and metal-aware backbone design; diffuses scaffolds around small molecules.",
  rfd3: "Modern all-atom diffusion for constrained binders, motifs, ligands, and interfaces.",
  rf3: "Open all-atom structure prediction for proteins and small-molecule complexes.",
  esmfold:
    "Fast MSA-free protein folding for inexpensive sequence structure screening.",
  disco:
    "Jointly co-designs protein sequence and structure around ligands, DNA, or RNA.",
  antifold:
    "Samples antibody and nanobody CDR sequences for an IMGT-numbered backbone.",
  thermompnn:
    "Scans point mutations and proposes variants predicted to improve protein stability.",
  pdbfixer:
    "Repairs missing atoms, residues, hydrogens, and nonstandard structure records.",
  esmif1:
    "Designs sequences for fixed backbones using structure-conditioned inverse folding.",
  evoef2:
    "Fast physics-based stability and protein-interface energy scoring without PyRosetta.",
  omegafold:
    "MSA-free single-sequence structure prediction with confidence estimates.",
  immunebuilder:
    "Specialized antibody, nanobody, and TCR structure prediction with residue errors.",
  "openmm-relax":
    "Prepares and energy-minimizes protein structures with an Amber force field.",
  p2rank:
    "Predicts likely ligand-binding pockets and their centers from protein structures.",
  freesasa:
    "Calculates solvent-accessible surface area for exposure and burial analysis.",
  "autodock-vina":
    "Docks small molecules into protein receptors with a fast CPU search.",
  plip: "Profiles hydrogen bonds, hydrophobics, salt bridges, and other ligand contacts.",
  esmc: "Newer protein language model than ESM-2 for embeddings and design scoring.",
  germinal:
    "De novo antibody and nanobody (VHH/scFv) design; license-gated, non-commercial.",
  foldseek:
    "Fast structure-based similarity search to find homologs across PDB and AFDB.",
  mmseqs2:
    "Fast protein sequence similarity search against supplied reference sequences.",
  hmmer:
    "Profile-HMM homology detection with sensitive significance and domain scores.",
  mafft:
    "Multiple protein sequence alignment for conservation and family analysis.",
  dssp: "Assigns secondary structure, hydrogen bonds, and residue solvent exposure.",
  fpocket:
    "Detects and ranks druggable cavities directly from a protein structure.",
  mdanalysis:
    "Computes structural geometry including RMSD, radius of gyration, and contacts.",
  pdb2pqr:
    "Adds hydrogens and assigns biomolecular protonation, charges, and radii.",
  propka:
    "Predicts residue pKa values and protonation behavior from protein structure.",
  apbs: "Calculates continuum electrostatics and solvation-energy summaries for proteins.",
  smina:
    "Docks ligands with Vina-compatible scoring and flexible CPU search options.",
  protparam:
    "Calculates molecular weight, pI, hydropathy, stability, charge, and composition.",
  parasail:
    "Fast pairwise protein alignment with global, local, and semi-global modes.",
  "cd-hit":
    "Clusters supplied protein sequences and removes redundancy at chosen identity.",
  diamond:
    "Rapid protein similarity search against references supplied in the request.",
  hhsuite:
    "Compares sequence profiles sensitively with HHalign and optional A3M depth.",
  prody:
    "Estimates collective motions and residue flexibility with elastic network models.",
  "pdb-tools":
    "Cleans, filters, canonicalizes, and validates coordinate records deterministically.",
  prodigy:
    "Predicts protein-protein binding affinity from contacts in an assembled complex.",
  arpeggio:
    "Classifies hydrogen bonds, ionic, aromatic, hydrophobic, and atomic contacts.",
  dockq:
    "Scores docking models against native references across one or more interfaces.",
};

/**
 * Returns the "good at" line for a slug, or the provided fallback when unknown.
 */
export function goodAt(slug: string, fallback?: string): string | undefined {
  return TOOL_GOOD_AT[slug] ?? fallback;
}
