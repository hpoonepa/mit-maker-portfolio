/**
 * The one-click demo job.
 *
 * Everything a first-time viewer needs to reach a real, running job with zero
 * typing. The values are not decorative: they are the canonical BindCraft
 * PD-L1 benchmark case:
 *
 *   • 5O45 is the RCSB entry for human PD-L1 (the checkpoint protein that
 *     Keytruda-class cancer drugs block).
 *   • Chain A is the PD-L1 copy in that structure.
 *   • Residues 56 / 115 / 123 sit on the face PD-1 normally binds, so a binder
 *     that touches them is a plausible blocker.
 *   • BindCraft is one of the twelve verified-runnable tools
 *     (`VERIFIED_RUNNABLE_TOOL_SLUGS` in @papercrane/trpc), so this submission
 *     always passes the server's runnability gate.
 *
 * `numDesigns` is deliberately small: the point is to reach a live run screen
 * quickly and cheaply, not to produce a campaign.
 */

export interface ExampleHotspot {
  chain: string;
  residues: number[];
}

export interface ExampleJobSpec {
  /** Verified-runnable tool slug: matches the catalog `toolId`. */
  toolId: string;
  /** Display name, used before the catalog has loaded. */
  toolName: string;
  /** Plain-language name of the protein. */
  targetName: string;
  /** One sentence a non-scientist can follow. */
  targetBlurb: string;
  /** 4-character RCSB id. */
  targetPdb: string;
  /** Which copy of the protein in that file. */
  targetChain: string;
  hotspots: ExampleHotspot[];
  /** How many binders to design in the demo run. */
  numDesigns: number;
}

export const EXAMPLE_JOB: ExampleJobSpec = {
  toolId: "bindcraft",
  toolName: "BindCraft",
  targetName: "PD-L1",
  targetBlurb:
    "PD-L1 is the protein tumours use to switch off immune cells: a binder that sticks to it is the basis of several cancer drugs.",
  targetPdb: "5O45",
  targetChain: "A",
  hotspots: [{ chain: "A", residues: [56, 115, 123] }],
  numDesigns: 2,
};

/** Seed list matching {@link EXAMPLE_JOB.numDesigns}: one seed per design. */
export function exampleSeeds(): number[] {
  return Array.from({ length: EXAMPLE_JOB.numDesigns }, (_v, i) => i + 1);
}

/**
 * The exact `jobs.submit` request payload for the demo run.
 *
 * Built as a literal rather than read out of wizard state so the one-click
 * path can submit immediately, without waiting for a render pass to flush the
 * prefilled state. `projectId` is threaded through `toolParams` when present so
 * the resulting job lands in the project the user launched from.
 */
export function exampleSubmission(projectId?: string) {
  return {
    toolId: EXAMPLE_JOB.toolId,
    request: {
      targetPdb: EXAMPLE_JOB.targetPdb,
      targetChain: EXAMPLE_JOB.targetChain,
      hotspots: EXAMPLE_JOB.hotspots.map((h) => ({
        chain: h.chain,
        residues: [...h.residues],
      })),
      seeds: exampleSeeds(),
      numDesigns: EXAMPLE_JOB.numDesigns,
      ...(projectId ? { toolParams: { projectId } } : {}),
    },
  };
}

/** "A56, A115, A123": how hotspots read in the UI. */
export function exampleHotspotLabel(): string {
  return EXAMPLE_JOB.hotspots
    .flatMap((h) => h.residues.map((r) => `${h.chain}${r}`))
    .join(", ");
}
