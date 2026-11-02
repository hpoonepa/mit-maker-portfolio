/**
 * Parser for the 5G51 V4 campaign (beta-optimized loss, helical template).
 * See project_5g51_v4_optimization.md in the memory index.
 *
 * The parser accepts the generic fixture shape defined in
 * `parsers/util.ts`. The user will adapt the `campaignMatch` predicate once
 * the concrete data path is known.
 */

import type { BenchmarkRun } from "../schema.js";
import { parseCampaignDir } from "./util.js";

export const sourceId = "5g51-v4" as const;

export async function parse(inputDir: string): Promise<BenchmarkRun[]> {
  return parseCampaignDir({
    inputDir,
    sourceId,
    campaignMatch: (raw) => {
      const c = raw.campaign.toLowerCase().replace(/_/g, "-");
      return c === "5g51-v4" || c === "5g51v4" || c === "fivegfiveone-v4";
    },
  });
}

export default { sourceId, parse };
