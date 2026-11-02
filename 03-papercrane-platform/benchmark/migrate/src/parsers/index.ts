/**
 * Parser registry. Add a new campaign by creating
 * `parsers/<campaign>.ts` exporting `{ sourceId, parse }`, then registering
 * it here.
 */

import type { BenchmarkRun } from "../schema.js";
import godV3b from "./god-v3b.js";
import fiveGFiveOneV4 from "./fivegfiveone-v4.js";
import rbx1 from "./rbx1.js";

export interface CampaignParser {
  sourceId: BenchmarkRun["source"];
  parse(inputDir: string): Promise<BenchmarkRun[]>;
}

const registry: Record<BenchmarkRun["source"], CampaignParser> = {
  "god-v3b": godV3b,
  "5g51-v4": fiveGFiveOneV4,
  "rbx1": rbx1,
};

/** Canonical list of source ids recognized by the CLI. */
export const ALL_SOURCES: BenchmarkRun["source"][] = [
  "god-v3b",
  "5g51-v4",
  "rbx1",
];

/** Return the parser for a given source id, or throw a helpful error. */
export function getParser(sourceId: string): CampaignParser {
  const parser = registry[sourceId as BenchmarkRun["source"]];
  if (!parser) {
    throw new Error(
      `unknown source '${sourceId}'. Valid sources: ${ALL_SOURCES.join(", ")} or 'all'.`,
    );
  }
  return parser;
}

/** Return every registered parser (used by `--source all`). */
export function allParsers(): CampaignParser[] {
  return ALL_SOURCES.map((id) => registry[id]);
}
