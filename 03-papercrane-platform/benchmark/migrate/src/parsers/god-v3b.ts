/**
 * Parser for the God V3B campaign (30-agent analysis, seeds 18/24/1/28/10
 * top-5; 28/60 seeds god-mode v1 baseline). See project_god_v3b_analysis.md
 * in the memory index.
 *
 * Real input layout has not yet been mapped onto disk; this parser accepts
 * the generic fixture shape defined in `parsers/util.ts`. The user will
 * adapt the `campaignMatch` predicate once the concrete data path is known.
 */

import type { BenchmarkRun } from "../schema.js";
import { parseCampaignDir } from "./util.js";

export const sourceId = "god-v3b" as const;

export async function parse(inputDir: string): Promise<BenchmarkRun[]> {
  return parseCampaignDir({
    inputDir,
    sourceId,
    campaignMatch: (raw) => {
      const c = raw.campaign.toLowerCase();
      return c === "god-v3b" || c === "god_v3b" || c === "godv3b";
    },
  });
}

export default { sourceId, parse };
