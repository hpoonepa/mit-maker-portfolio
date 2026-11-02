import type { components } from "../../api/types.generated";
import { numberValue, recordValue, stringArrayValue, stringValue as reportStringValue } from "../reports/report-model";

type TimelineItem = components["schemas"]["TimelineItem"];
export type CorrectionTarget = components["schemas"]["CorrectionTargetDetail"];
export type CorrectionImpact = components["schemas"]["CorrectionImpactDetail"];
export type ReviewEntityType = components["schemas"]["ReviewItemDetail"]["reviewEntityType"];


export interface ReviewItem {
  id: string;
  targetType: string;
  kind: string;
  timestampUs: number;
  endUs: number | null;
  confidence: number | null;
  issue: string;
  evidenceIds: string[];
  provenance: "observed" | "reconstructed" | "ambiguous" | "unavailable";
  probabilities: Record<string, number>;
  reasons: string[];
  evidenceStartTimestampUs: number;
  evidenceEndTimestampUs: number;
  evidenceStartFrameIndex: number | null;
  evidenceEndFrameIndex: number | null;
  invalidatedSections: string[];
  invalidatedStats: string[];
  summary: Record<string, unknown>;
  commandTargets: Record<string, CorrectionTarget>;
  reviewEntityType: ReviewEntityType;
  reviewEntityId: string;
  reviewStatus: string;
  commandImpacts: Record<string, CorrectionImpact>;
}

const IMPACT_PRIORITY: Record<string, number> = {
  rally_boundary: 0,
  player_identity: 0,
  identity: 0,
  ball_seam: 0,
  outcome: 1,
  hitter: 2,
  shot_type: 2,
  type: 2,
  accept: 3,
};

function stringValue(summary: Record<string, unknown>, ...names: string[]): string | null {
  for (const name of names) {
    const value = summary[name];
    if (typeof value === "string") return value;
  }
  return null;
}

function normalizedReviewEntityType(
  value: string | null,
  fallback: ReviewEntityType,
): ReviewEntityType {
  return value === "error_candidate" || value === "shot" || value === "rally"
    ? value
    : fallback;
}

function confidenceValue(summary: Record<string, unknown>): number | null {
  const value = summary.confidence;
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : null;
}

function numericRecord(value: unknown): Record<string, number> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return {};
  const result: Record<string, number> = {};
  for (const [name, candidate] of Object.entries(value)) {
    if (typeof candidate === "number" && Number.isFinite(candidate)) result[name] = candidate;
  }
  return result;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function optionalNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function correctionTargets(value: unknown): Record<string, CorrectionTarget> {
  const source = recordValue(value);
  if (source === null) return {};
  const targets: Record<string, CorrectionTarget> = {};
  for (const [command, candidate] of Object.entries(source)) {
    const target = recordValue(candidate);
    if (target === null) continue;
    const targetType = reportStringValue(target, "targetType");
    const targetId = reportStringValue(target, "targetId");
    const sourceTimestampUs = numberValue(target, "sourceTimestampUs");
    const evidenceStartTimestampUs = numberValue(target, "evidenceStartTimestampUs");
    const evidenceEndTimestampUs = numberValue(target, "evidenceEndTimestampUs");
    if (targetType === null || targetId === null || sourceTimestampUs === null || evidenceStartTimestampUs === null || evidenceEndTimestampUs === null) continue;
    targets[command] = {
      targetType,
      targetId,
      sourceTimestampUs,
      sourceEvidenceIds: stringArrayValue(target, "sourceEvidenceIds"),
      evidenceStartTimestampUs,
      evidenceEndTimestampUs,
      evidenceStartFrameIndex: numberValue(target, "evidenceStartFrameIndex"),
      evidenceEndFrameIndex: numberValue(target, "evidenceEndFrameIndex"),
    };
  }
  return targets;
}

function correctionImpacts(value: unknown): Record<string, CorrectionImpact> {
  const source = recordValue(value);
  if (source === null) return {};
  const impacts: Record<string, CorrectionImpact> = {};
  for (const [command, candidate] of Object.entries(source)) {
    const impact = recordValue(candidate);
    if (impact === null) continue;
    impacts[command] = {
      invalidatedSections: stringArrayValue(impact, "invalidatedSections"),
      invalidatedStats: stringArrayValue(impact, "invalidatedStats"),
    };
  }
  return impacts;
}

function visibleReviewItem(event: TimelineItem): ReviewItem | null {
  if (event.id === null || event.id === undefined) return null;
  const summary = event.summary ?? {};
  const status = stringValue(summary, "review_status", "reviewStatus");
  if (status === "accepted" || status === "rejected") return null;
  const confidence = confidenceValue(summary);
  if (summary.review_required !== true && summary.reviewRequired !== true && (confidence === null || confidence >= 0.5)) return null;
  const issue = stringValue(summary, "issue", "review_reason")
    ?? (event.kind === "rally" ? "rally_boundary" : event.kind === "error" ? "accept" : "shot_type");
  const provenanceValue = stringValue(summary, "provenance", "source_state", "sourceState");
  const provenance = provenanceValue === "observed" || provenanceValue === "reconstructed" || provenanceValue === "ambiguous" ? provenanceValue : "unavailable";
  return {
    id: event.id,
    targetType: stringValue(summary, "targetType", "target_type") ?? (event.kind === "rally" ? "rally" : event.kind === "error" ? "error_candidate" : "shot"),
    kind: event.kind,
    timestampUs: event.timestampUs,
    endUs: event.endUs ?? null,
    confidence,
    issue,
    evidenceIds: event.evidenceIds ?? [],
    provenance,
    probabilities: numericRecord(summary.probabilities),
    reasons: stringList(summary.reasons),
    evidenceStartTimestampUs: optionalNumber(summary.evidenceStartTimestampUs) ?? event.timestampUs,
    evidenceEndTimestampUs: optionalNumber(summary.evidenceEndTimestampUs) ?? event.endUs ?? event.timestampUs,
    evidenceStartFrameIndex: optionalNumber(summary.evidenceStartFrameIndex),
    evidenceEndFrameIndex: optionalNumber(summary.evidenceEndFrameIndex),
    invalidatedSections: stringList(summary.invalidatedSections),
    invalidatedStats: stringList(summary.invalidatedStats),
    commandTargets: correctionTargets(summary.commandTargets),
    commandImpacts: correctionImpacts(summary.commandImpacts),
    summary,
    reviewEntityType: normalizedReviewEntityType(
      stringValue(summary, "reviewEntityType", "review_entity_type"),
      event.kind === "rally" ? "rally" : event.kind === "shot" ? "shot" : "error_candidate",
    ),
    reviewEntityId: stringValue(summary, "reviewEntityId", "review_entity_id") ?? event.id,
    reviewStatus: status ?? "pending",
  };
}

export function buildReviewQueue(serverItems: readonly ReviewItem[], events: readonly TimelineItem[]): ReviewItem[] {
  const queue = [...serverItems];
  const reviewEntityKey = (item: ReviewItem): string => `${item.reviewEntityType}\u0000${item.reviewEntityId}`;
  const known = new Set(queue.map(reviewEntityKey));
  for (const event of events) {
    const item = visibleReviewItem(event);
    const key = item === null ? null : reviewEntityKey(item);
    if (item !== null && key !== null && !known.has(key)) {
      known.add(key);
      queue.push(item);
    }
  }
  return queue.sort((left, right) => {
    const impact = (IMPACT_PRIORITY[left.issue] ?? 3) - (IMPACT_PRIORITY[right.issue] ?? 3);
    if (impact !== 0) return impact;
    const confidence = (left.confidence ?? 1) - (right.confidence ?? 1);
    if (confidence !== 0) return confidence;
    if (left.timestampUs !== right.timestampUs) return left.timestampUs - right.timestampUs;
    return left.id.localeCompare(right.id);
  });
}
