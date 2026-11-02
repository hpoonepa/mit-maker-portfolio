export type PublicToolStatus = "ga" | "beta";

export type PublicTool = {
  slug: string;
  name: string;
  version: string;
  category: string;
  license: string;
  status: PublicToolStatus;
  runnable: boolean;
};

/** Public projection of the checked-in tool manifests; keep it in lockstep with the platform. */
export const PUBLIC_TOOL_CATALOG: PublicTool[] = [
  { slug: "alphafold3", name: "AlphaFold 3 (Protenix)", version: "protenix-1.0.4", category: "structure_prediction", license: "Apache-2.0 (Protenix, ByteDance)", status: "ga", runnable: true },
  { slug: "antifold", name: "AntiFold", version: "0.3.1", category: "sequence_design", license: "BSD-3-Clause", status: "beta", runnable: true },
  { slug: "apbs", name: "APBS", version: "3.4.1", category: "embedding_scoring", license: "BSD-3-Clause", status: "beta", runnable: true },
  { slug: "arpeggio", name: "PDBe Arpeggio", version: "1.4.4", category: "embedding_scoring", license: "GPL-3.0-only", status: "beta", runnable: true },
  { slug: "autodock-vina", name: "AutoDock Vina", version: "1.2.7", category: "structure_prediction", license: "Apache-2.0", status: "beta", runnable: true },
  { slug: "bindcraft", name: "BindCraft", version: "1.2.0", category: "binder_design", license: "MIT", status: "ga", runnable: true },
  { slug: "boltz1", name: "Boltz-1", version: "1.0.0", category: "structure_prediction", license: "MIT", status: "ga", runnable: true },
  { slug: "boltz2", name: "Boltz-2", version: "2.0.0", category: "structure_prediction", license: "MIT", status: "ga", runnable: true },
  { slug: "boltzgen", name: "BoltzGen", version: "0.1.0", category: "binder_design", license: "MIT", status: "ga", runnable: true },
  { slug: "cd-hit", name: "CD-HIT", version: "4.8.1", category: "embedding_scoring", license: "GPL-2.0-only", status: "beta", runnable: true },
  { slug: "chai1", name: "Chai-1", version: "1.0.0", category: "structure_prediction", license: "non-commercial (chaiDiscovery/chai-1 terms)", status: "ga", runnable: true },
  { slug: "chroma", name: "Chroma", version: "1.0.0", category: "backbone_generation", license: "Apache-2.0", status: "ga", runnable: true },
  { slug: "diamond", name: "DIAMOND", version: "2.2.4", category: "embedding_scoring", license: "GPL-3.0-only", status: "beta", runnable: true },
  { slug: "disco", name: "DISCO", version: "1.0.0", category: "backbone_generation", license: "Apache-2.0", status: "beta", runnable: true },
  { slug: "dockq", name: "DockQ", version: "2.1.3", category: "embedding_scoring", license: "MIT", status: "beta", runnable: true },
  { slug: "dssp", name: "DSSP", version: "4.6.1", category: "embedding_scoring", license: "BSD-2-Clause", status: "beta", runnable: true },
  { slug: "esm2", name: "ESM-2", version: "650M-UR50D", category: "embedding_scoring", license: "MIT", status: "ga", runnable: true },
  { slug: "esmc", name: "ESM-C 300M", version: "300M-2024-12", category: "embedding_scoring", license: "MIT", status: "beta", runnable: true },
  { slug: "esmfold", name: "ESMFold", version: "1.0", category: "structure_prediction", license: "MIT", status: "beta", runnable: true },
  { slug: "esmif1", name: "ESM-IF1", version: "2.0.0", category: "sequence_design", license: "MIT", status: "beta", runnable: true },
  { slug: "evoef2", name: "EvoEF2", version: "2026.6.22", category: "embedding_scoring", license: "MIT", status: "beta", runnable: true },
  { slug: "foldseek", name: "Foldseek", version: "10.941cd33", category: "embedding_scoring", license: "GPL-3.0", status: "beta", runnable: true },
  { slug: "fpocket", name: "fpocket", version: "4.2.3", category: "embedding_scoring", license: "MIT", status: "beta", runnable: true },
  { slug: "freesasa", name: "FreeSASA", version: "2.2.1", category: "embedding_scoring", license: "MIT", status: "beta", runnable: true },
  { slug: "germinal", name: "Germinal", version: "1.0.0", category: "binder_design", license: "Apache-2.0", status: "beta", runnable: false },
  { slug: "hhsuite", name: "HH-suite", version: "3.3.0", category: "embedding_scoring", license: "GPL-3.0-only", status: "beta", runnable: true },
  { slug: "hmmer", name: "HMMER phmmer", version: "3.4", category: "embedding_scoring", license: "BSD-3-Clause", status: "beta", runnable: true },
  { slug: "immunebuilder", name: "ImmuneBuilder", version: "1.2", category: "structure_prediction", license: "BSD-3-Clause", status: "beta", runnable: true },
  { slug: "ligandmpnn", name: "LigandMPNN", version: "1.0.0", category: "sequence_design", license: "MIT", status: "ga", runnable: true },
  { slug: "mafft", name: "MAFFT", version: "7.526", category: "embedding_scoring", license: "BSD-3-Clause", status: "beta", runnable: true },
  { slug: "mdanalysis", name: "MDAnalysis", version: "2.10.0", category: "embedding_scoring", license: "LGPL-3.0-or-later", status: "beta", runnable: true },
  { slug: "mmseqs2", name: "MMseqs2", version: "18-8cc5c", category: "embedding_scoring", license: "MIT", status: "beta", runnable: true },
  { slug: "omegafold", name: "OmegaFold", version: "313c873", category: "structure_prediction", license: "Apache-2.0", status: "beta", runnable: true },
  { slug: "openmm-relax", name: "OpenMM Relax", version: "8.5.2", category: "structure_prediction", license: "MIT/LGPL", status: "beta", runnable: true },
  { slug: "p2rank", name: "P2Rank", version: "2.5.1", category: "embedding_scoring", license: "MIT", status: "beta", runnable: true },
  { slug: "parasail", name: "Parasail", version: "1.3.4", category: "embedding_scoring", license: "BSD-3-Clause", status: "beta", runnable: true },
  { slug: "pdb-tools", name: "pdb-tools", version: "2.7.0", category: "embedding_scoring", license: "Apache-2.0", status: "beta", runnable: true },
  { slug: "pdb2pqr", name: "PDB2PQR", version: "3.7.1", category: "structure_prediction", license: "BSD-3-Clause", status: "beta", runnable: true },
  { slug: "pdbfixer", name: "PDBFixer", version: "1.12", category: "structure_prediction", license: "MIT", status: "beta", runnable: true },
  { slug: "plip", name: "PLIP", version: "3.0.0", category: "embedding_scoring", license: "GPL-2.0-only", status: "beta", runnable: true },
  { slug: "prodigy", name: "PRODIGY", version: "2.4.0", category: "embedding_scoring", license: "Apache-2.0", status: "beta", runnable: true },
  { slug: "prody", name: "ProDy", version: "2.6.1", category: "embedding_scoring", license: "MIT", status: "beta", runnable: true },
  { slug: "propka", name: "PROPKA", version: "3.5.1", category: "embedding_scoring", license: "LGPL-2.1-only", status: "beta", runnable: true },
  { slug: "proteinmpnn", name: "ProteinMPNN", version: "1.0.1", category: "sequence_design", license: "MIT", status: "ga", runnable: true },
  { slug: "protparam", name: "ProtParam", version: "1.87", category: "embedding_scoring", license: "Biopython License Agreement", status: "beta", runnable: true },
  { slug: "rf3", name: "RoseTTAFold3", version: "0.1.9", category: "structure_prediction", license: "BSD-3-Clause", status: "beta", runnable: true },
  { slug: "rfd3", name: "RFdiffusion3", version: "0.1.9", category: "binder_design", license: "BSD-3-Clause", status: "beta", runnable: true },
  { slug: "rfdiffusion", name: "RFdiffusion", version: "1.1.0", category: "backbone_generation", license: "BSD-3-Clause", status: "ga", runnable: true },
  { slug: "rfdiffusionaa", name: "RFdiffusion All-Atom", version: "1.0.0", category: "backbone_generation", license: "BSD-3-Clause", status: "beta", runnable: true },
  { slug: "smina", name: "smina", version: "2019.10.15", category: "structure_prediction", license: "GPL-2.0-only", status: "beta", runnable: true },
  { slug: "solublempnn", name: "SolubleMPNN", version: "1.0.1", category: "sequence_design", license: "MIT", status: "ga", runnable: true },
  { slug: "thermompnn", name: "ThermoMPNN", version: "2026.08.10", category: "sequence_design", license: "MIT", status: "beta", runnable: true },
];
