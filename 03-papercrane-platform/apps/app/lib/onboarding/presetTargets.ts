/**
 * First-run preset targets.
 *
 * Three well-characterised targets the user can pick if they don't have
 * a PDB of their own yet. Each preset carries the PDB id, the relevant
 * chain, a small set of hotspot residues (used by BindCraft's default
 * config), and a one-sentence "why this matters" line for the UI card.
 *
 * Hotspots are encoded as single-letter-chain + integer residue (e.g.
 * `A56`) to match BindCraft / RFdiffusion selector syntax.
 *
 * Picks
 * -----
 *   - **PD-L1** (PDB 4ZQK, chain A): canonical checkpoint target, shows
 *     up in every binder design benchmark.
 *   - **SARS-CoV-2 RBD** (PDB 6M0J, chain E): widely replicated binder
 *     results, easy sanity-check for new users.
 *   - **IL-7Rα** (PDB 3UP1, chain A): extracellular cytokine receptor;
 *     gives users a "harder" preset so the tier-to-compute mapping makes
 *     sense on first use.
 */

export interface PresetTarget {
  id: string;
  name: string;
  pdbId: string;
  chain: string;
  hotspots: string[];
  rationale: string;
}

export const PRESET_TARGETS: readonly PresetTarget[] = [
  {
    id: "pdl1",
    name: "PD-L1 (checkpoint)",
    pdbId: "4ZQK",
    chain: "A",
    hotspots: ["A54", "A56", "A115", "A123"],
    rationale:
      "Canonical immune-checkpoint target. Lots of literature binders: a reliable first run.",
  },
  {
    id: "rbd",
    name: "SARS-CoV-2 spike RBD",
    pdbId: "6M0J",
    chain: "E",
    hotspots: ["E453", "E455", "E486", "E493", "E501"],
    rationale:
      "The most-replicated binder benchmark of the last 5 years. Fast, easy to sanity-check.",
  },
  {
    id: "il7ra",
    name: "IL-7Rα (cytokine receptor)",
    pdbId: "3UP1",
    chain: "A",
    hotspots: ["A58", "A80", "A138", "A141"],
    rationale:
      "Extracellular cytokine receptor. Harder surface: a realistic stretch target on first use.",
  },
] as const;

export function getPresetTarget(id: string): PresetTarget | undefined {
  return PRESET_TARGETS.find((p) => p.id === id);
}
