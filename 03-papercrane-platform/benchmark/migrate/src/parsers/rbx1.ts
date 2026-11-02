/**
 * Parser for the RBX1 campaign (PDB 2LGV, 20-seed Modal + Vast.ai redesign).
 * See project_rbx1_campaign_status.md + project_construct_redesign_status.md
 * in the memory index.
 *
 * The parser accepts the generic fixture shape defined in
 * `parsers/util.ts`. The user will adapt the `campaignMatch` predicate once
 * the concrete data path is known.
 */

import type { BenchmarkRun } from "../schema.js";
import { parseCampaignDir } from "./util.js";

export const sourceId = "rbx1" as const;

export async function parse(inputDir: string): Promise<BenchmarkRun[]> {
  return parseCampaignDir({
    inputDir,
    sourceId,
    campaignMatch: (raw) => {
      const c = raw.campaign.toLowerCase();
      return c === "rbx1" || c === "rbx-1" || c === "rbx_1";
    },
  });
}

export default { sourceId, parse };
