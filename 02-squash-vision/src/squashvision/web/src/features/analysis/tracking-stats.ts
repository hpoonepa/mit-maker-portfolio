import type { components } from "../../api/types.generated";

export type TrackingPlayerStats = components["schemas"]["TrackedPlayerStats"];
export type TrackingContact = components["schemas"]["TrackedContactStats"];
export type TrackingStats = components["schemas"]["TrackingStatsDetail"];

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error("Invalid tracking statistics");
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  if (typeof value !== "string") throw new Error("Invalid tracking text");
  return value;
}
function nullableText(value: unknown): string | null { return value === null ? null : text(value); }
function number(value: unknown, maximum = Number.MAX_VALUE): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > maximum) throw new Error("Invalid tracking measurement");
  return value;
}
function integer(value: unknown): number {
  const result = number(value);
  if (!Number.isSafeInteger(result)) throw new Error("Invalid tracking index");
  return result;
}
function nullableNumber(value: unknown): number | null { return value === null ? null : number(value); }
function nullableInteger(value: unknown): number | null { return value === null ? null : integer(value); }
function boolean(value: unknown): boolean {
  if (typeof value !== "boolean") throw new Error("Invalid tracking state");
  return value;
}
function playerId(value: unknown): "A" | "B" {
  if (value !== "A" && value !== "B") throw new Error("Invalid player identity");
  return value;
}
function array(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new Error("Invalid tracking list");
  return value;
}

export function decodeTrackingStats(value: unknown): TrackingStats {
  const data = object(value);
  const players = array(data.players).map((candidate): TrackingPlayerStats => {
    const item = object(candidate);
    if (item.identityVerified !== false) throw new Error("Unsupported verified identity claim");
    return {
      playerId: playerId(item.playerId), distanceM: nullableNumber(item.distanceM),
      trackedSeconds: number(item.trackedSeconds), coverage: number(item.coverage, 1),
      observedSamples: integer(item.observedSamples), usedSamples: integer(item.usedSamples),
      excludedSamples: integer(item.excludedSamples), contactCount: integer(item.contactCount),
      identityVerified: false,
    };
  });
  if (players.length !== 2 || new Set(players.map((player) => player.playerId)).size !== 2) throw new Error("Incomplete player statistics");
  const contacts = array(data.contacts).map((candidate): TrackingContact => {
    const item = object(candidate);
    let position: [number, number] | null = null;
    if (item.position !== null) {
      const point = array(item.position);
      if (point.length !== 2) throw new Error("Invalid contact position");
      position = [number(point[0], 6.4), number(point[1], 9.75)];
    }
    if (item.positionMethod !== "hitter_feet_at_contact") throw new Error("Unsupported contact position");
    return {
      id: text(item.id), timestampUs: integer(item.timestampUs), proxyTimestampUs: nullableInteger(item.proxyTimestampUs),
      sourceFrameIndex: nullableInteger(item.sourceFrameIndex), hitter: item.hitter === null ? null : playerId(item.hitter),
      hitterConfidence: number(item.hitterConfidence, 1), confidence: number(item.confidence, 1), position,
      positionMethod: item.positionMethod, reason: nullableText(item.reason), reviewRequired: boolean(item.reviewRequired),
    };
  });
  if (new Set(contacts.map((contact) => contact.id)).size !== contacts.length) throw new Error("Duplicate contacts");
  const speed = object(data.ballSpeed);
  const result: TrackingStats = {
    reportRevision: integer(data.reportRevision), predictionRevision: integer(data.predictionRevision),
    calibrationRevision: nullableInteger(data.calibrationRevision), calibrationAvailable: boolean(data.calibrationAvailable),
    calibrationReason: nullableText(data.calibrationReason), startUs: integer(data.startUs), endUs: integer(data.endUs),
    players, contacts,
    ballSpeed: {
      medianMps: nullableNumber(speed.medianMps), p90Mps: nullableNumber(speed.p90Mps), sampleCount: integer(speed.sampleCount), excludedSamples: integer(speed.excludedSamples),
      trackedSeconds: number(speed.trackedSeconds), coverage: number(speed.coverage, 1), method: text(speed.method), reason: nullableText(speed.reason),
    },
    coordinateSystem: text(data.coordinateSystem), limitations: array(data.limitations).map(text),
  };
  if (result.endUs < result.startUs) throw new Error("Invalid tracking interval");
  if (!result.calibrationAvailable && (players.some((player) => player.distanceM !== null) || contacts.some((contact) => contact.position !== null) || result.ballSpeed.medianMps !== null || result.ballSpeed.p90Mps !== null)) throw new Error("Uncalibrated metric measurements");
  return result;
}
