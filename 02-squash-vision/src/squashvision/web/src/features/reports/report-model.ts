import type { components } from "../../api/types.generated";

export type MatchReport = components["schemas"]["MatchReport"];
export type ReportSection = components["schemas"]["ReportSection"];

export interface ReportViewProps {
  report: MatchReport;
  onSeekEvidence: (evidenceId: string) => void;
}

export interface Availability {
  available: boolean;
  reason: string | null;
}

export function reportSection(report: MatchReport, name: string): ReportSection | null {
  return report.sections[name] ?? null;
}

export function recordValue(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

export function nestedRecord(record: Record<string, unknown>, name: string): Record<string, unknown> | null {
  const value = record[name];
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

export function arrayValue(record: Record<string, unknown>, name: string): unknown[] {
  const value = record[name];
  return Array.isArray(value) ? value : [];
}

export function numberValue(record: Record<string, unknown>, name: string): number | null {
  const value = record[name];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function stringValue(record: Record<string, unknown>, name: string): string | null {
  const value = record[name];
  return typeof value === "string" ? value : null;
}

export function booleanValue(record: Record<string, unknown>, name: string): boolean | null {
  const value = record[name];
  return typeof value === "boolean" ? value : null;
}

export function stringArrayValue(record: Record<string, unknown>, name: string): string[] {
  return arrayValue(record, name).filter((item): item is string => typeof item === "string");
}

export function availability(payload: Record<string, unknown>): Availability {
  const state = nestedRecord(payload, "availability");
  if (state === null) return { available: true, reason: null };
  const available = booleanValue(state, "available");
  return {
    available: available === true,
    reason: stringValue(state, "reason") ?? (available === true ? null : "unknown_prerequisite"),
  };
}

export function metricValue(payload: Record<string, unknown>, name: string): { available: boolean; value: number | null; reason: string | null } {
  const direct = numberValue(payload, name);
  if (direct !== null) return { available: true, value: direct, reason: null };
  const metric = nestedRecord(payload, name);
  if (metric === null) return { available: false, value: null, reason: "not_published" };
  return {
    available: booleanValue(metric, "available") === true && numberValue(metric, "value") !== null,
    value: numberValue(metric, "value"),
    reason: stringValue(metric, "reason"),
  };
}

export function readableReason(reason: string | null): string {
  return (reason ?? "unknown prerequisite").replaceAll("_", " ");
}

export function unavailableAction(reason: string | null): string {
  const value = reason ?? "unknown_prerequisite";
  if (value.includes("processing") || value.includes("prediction") || value.includes("legacy")) {
    return "Finish processing this match to publish the required evidence.";
  }
  if (value.includes("calibration") || value.includes("floor")) {
    return "Calibrate the court with an active, current revision to enable this view.";
  }
  if (value.includes("review") || value.includes("candidate")) {
    return "Review the pending candidates to make this value available.";
  }
  return "No sufficient sample is available in this report revision. Continue processing or collect more measured evidence.";
}
