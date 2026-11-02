import type { components } from "../../api/types.generated";
import type { PlaybackImpactMarker } from "./EvidenceWorkspace";
import { smoothSpeedSamples } from "./speed-display";

export type PlaybackTimeline = components["schemas"]["TrackingTimelineDetail"];
export type PlaybackContact = components["schemas"]["PlaybackContact"];
type PlayerSample = components["schemas"]["PlaybackPlayerSample"];
type SpeedSample = components["schemas"]["PlaybackBallSpeed"];
type FrameMap = components["schemas"]["FrameMapDetail"];
type PlayerId = "A" | "B";

const record = (value: unknown): Record<string, unknown> => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error("Invalid playback data");
  return value as Record<string, unknown>;
};
const finite = (value: unknown, max = Number.MAX_SAFE_INTEGER): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= max;
const integer = (value: unknown): value is number => finite(value) && Number.isSafeInteger(value);
const nullable = (value: unknown, check: (v: unknown) => boolean): boolean => value === null || check(value);
const point = (value: unknown): boolean => Array.isArray(value) && value.length === 2 && value.every((n) => typeof n === "number" && Number.isFinite(n));
const courtPoint = (value: unknown): boolean => point(value) && (value as number[])[0] >= 0 && (value as number[])[0] <= 6.4 && (value as number[])[1] >= 0 && (value as number[])[1] <= 9.75;
const playerId = (value: unknown): value is PlayerId => value === "A" || value === "B";
const string = (value: unknown): boolean => typeof value === "string";
function assert(condition: boolean): asserts condition { if (!condition) throw new Error("Invalid playback data"); }
function list(value: unknown): Record<string, unknown>[] { assert(Array.isArray(value)); return value.map(record); }

export function decodePlaybackTimeline(value: unknown): PlaybackTimeline {
  const data = record(value);
  assert([data.reportRevision, data.predictionRevision, data.startUs, data.endUs, data.durationUs, data.landingCount].every(integer));
  assert(Number(data.endUs) > Number(data.startUs) && nullable(data.calibrationRevision, integer) && typeof data.calibrationAvailable === "boolean");
  assert(nullable(data.calibrationReason, string) && nullable(data.landingReason, string));
  assert(data.ballSpeedMethod === "court_scaled_image_speed" && Array.isArray(data.limitations) && data.limitations.every(string));
  const players = list(data.players);
  assert(players.length === 2 && new Set(players.map((p) => p.playerId)).size === 2);
  players.forEach((p) => assert(playerId(p.playerId) && nullable(p.baselineDistanceM, finite) && finite(p.baselineTrackedSeconds)));
  list(data.playerSamples).forEach((p) => {
    assert(playerId(p.playerId) && integer(p.timestampUs) && nullable(p.sourceFrameIndex, integer));
    assert(nullable(p.proxyTimestampUs, integer) && nullable(p.proxyEndTimestampUs, integer));
    assert(p.proxyTimestampUs === null || p.proxyEndTimestampUs === null || Number(p.proxyEndTimestampUs) > Number(p.proxyTimestampUs));
    assert(nullable(p.position, courtPoint) && nullable(p.cumulativeDistanceM, finite) && finite(p.trackedSeconds) && nullable(p.positionReason, string));
  });
  list(data.ballSpeeds).forEach((s) => {
    assert(integer(s.timestampUs) && integer(s.intervalStartUs) && Number(s.intervalStartUs) < Number(s.timestampUs) && integer(s.sourceFrameIndex) && finite(s.speedMps));
    assert(nullable(s.proxyTimestampUs, integer) && nullable(s.proxyEndTimestampUs, integer));
    assert(s.proxyTimestampUs === null || s.proxyEndTimestampUs === null || Number(s.proxyEndTimestampUs) > Number(s.proxyTimestampUs));
  });
  const contacts = list(data.contacts);
  assert(new Set(contacts.map((c) => c.id)).size === contacts.length);
  contacts.forEach((c) => {
    assert(typeof c.id === "string" && ["racket", "floor", "front_wall", "unknown"].includes(String(c.kind)));
    assert(integer(c.timestampUs) && nullable(c.proxyTimestampUs, integer) && nullable(c.sourceFrameIndex, integer) && integer(c.timingUncertaintyUs));
    assert(finite(c.confidence, 1) && finite(c.hitterConfidence, 1) && nullable(c.hitter, playerId));
    if (c.shotHitter !== undefined) {
      assert(nullable(c.shotHitter, playerId) && nullable(c.shotContactId, string) && finite(c.shotHitterConfidence, 1));
      assert(c.shotHitter === null ? c.shotContactId === null && c.shotHitterConfidence === 0 : typeof c.shotContactId === "string" && c.shotContactId.length > 0 && Number(c.shotHitterConfidence) > 0);
    }
    assert(nullable(c.ballImagePosition, point) && nullable(c.playerPosition, courtPoint) && nullable(c.floorPosition, courtPoint));
    assert(nullable(c.imageWidth, integer) && nullable(c.imageHeight, integer) && nullable(c.positionReason, string));
    assert(c.wallImageFraction === undefined || nullable(c.wallImageFraction, (n) => finite(n, 1)));
    assert(c.wallPosition === undefined || nullable(c.wallPosition, point));
    assert(typeof c.provenance === "string" && c.provenance.length > 0 && typeof c.reviewRequired === "boolean");
    assert(c.kind === "floor" || c.floorPosition === null);
  });
  return data as unknown as PlaybackTimeline;
}

export function decodePlaybackFrameMap(value: unknown): FrameMap {
  const data = record(value);
  assert(integer(data.startUs) && integer(data.endUs));
  let previous = -1;
  list(data.items).forEach((item) => {
    assert(integer(item.proxyTimestampUs) && integer(item.sourceTimestampUs) && integer(item.sourceFrameIndex));
    assert(Number(item.proxyTimestampUs) > previous);
    previous = Number(item.proxyTimestampUs);
  });
  return data as unknown as FrameMap;
}

export interface PlaybackIndex {
  timeline: PlaybackTimeline;
  players: Record<PlayerId, PlayerSample[]>;
  speeds: SpeedSample[];
  contacts: PlaybackContact[];
}
const proxySort = (a: { proxyTimestampUs: number | null }, b: { proxyTimestampUs: number | null }): number => a.proxyTimestampUs! - b.proxyTimestampUs!;
export function indexPlayback(timeline: PlaybackTimeline): PlaybackIndex {
  return {
    timeline,
    players: Object.fromEntries((["A", "B"] as const).map((id) => [id, timeline.playerSamples.filter((p) => p.playerId === id && p.proxyTimestampUs !== null).sort(proxySort)])) as Record<PlayerId, PlayerSample[]>,
    speeds: smoothSpeedSamples(timeline.ballSpeeds.filter((s) => s.proxyTimestampUs !== null && s.proxyEndTimestampUs !== null).sort(proxySort), timeline.contacts.flatMap(c=>c.proxyTimestampUs === null ? [] : [c.proxyTimestampUs])),
    contacts: timeline.contacts.filter((c) => c.proxyTimestampUs !== null).sort(proxySort),
  };
}
function pastIndex<T extends { proxyTimestampUs: number | null }>(rows: readonly T[], timeUs: number): number {
  let low = 0, high = rows.length;
  while (low < high) { const mid = (low + high) >>> 1; if (rows[mid].proxyTimestampUs! <= timeUs) low = mid + 1; else high = mid; }
  return low - 1;
}
export interface PlaybackSnapshot {
  players: Array<{ playerId: PlayerId; distanceM: number | null; trackedSeconds: number; position: [number, number] | null; trail: [number, number][] }>;
  speedMps: number | null;
  contacts: PlaybackContact[];
  activeContact: PlaybackContact | null;
  impactMarker: PlaybackImpactMarker | null;
}
export function playbackAt(index: PlaybackIndex, timeUs: number): PlaybackSnapshot {
  const players = (["A", "B"] as const).map((id) => {
    const rows = index.players[id];
    const at = pastIndex(rows, timeUs);
    const latest = rows[at];
    const baseline = index.timeline.players.find((p) => p.playerId === id)!;
    const present = latest !== undefined && latest.proxyEndTimestampUs !== null && timeUs < latest.proxyEndTimestampUs;
    const trail: [number, number][] = [];
    if (present && latest.position !== null) {
      for (let n = at; n >= 0 && rows[n].proxyTimestampUs! >= timeUs - 800_000; n--) {
        const row = rows[n];
        if (row.position === null || (n < at && (row.proxyEndTimestampUs === null || row.proxyEndTimestampUs < rows[n + 1].proxyTimestampUs!))) break;
        trail.unshift(row.position);
      }
    }
    return { playerId: id, distanceM: latest === undefined ? baseline.baselineDistanceM : latest.cumulativeDistanceM, trackedSeconds: latest?.trackedSeconds ?? baseline.baselineTrackedSeconds, position: present ? latest.position : null, trail };
  });
  const speed = index.speeds[pastIndex(index.speeds, timeUs)];
  const speedMps = speed !== undefined && timeUs < speed.proxyEndTimestampUs! ? speed.speedMps : null;
  const contacts = index.contacts.slice(0, pastIndex(index.contacts, timeUs) + 1);
  const last = contacts.at(-1) ?? null;
  const activeContact = last !== null && timeUs - last.proxyTimestampUs! < 250_000 ? last : null;
  const impactMarker = activeContact?.ballImagePosition !== null && activeContact !== null && activeContact.imageWidth !== null && activeContact.imageWidth > 0 && activeContact.imageHeight !== null && activeContact.imageHeight > 0 ? {
    imagePosition: activeContact.ballImagePosition!, sourceWidth: activeContact.imageWidth, sourceHeight: activeContact.imageHeight, kind: activeContact.kind, timestampUs: activeContact.proxyTimestampUs!,
  } : null;
  return { players, speedMps, contacts, activeContact, impactMarker };
}
