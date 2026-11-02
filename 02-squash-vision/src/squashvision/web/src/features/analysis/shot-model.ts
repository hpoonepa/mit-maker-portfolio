import type { PlaybackContact, PlaybackTimeline } from "./playback-model";
import { projectWall } from "./wall-calibration";
export type Point = [number, number];
export type ShotType = "drive" | "crosscourt" | "drop" | "boast" | "lob" | "unknown";
export interface ShotImpact { timeUs: number; image: Point | null; position: Point | null }
export interface ReviewShot {
  id: string; contactUs: number; hitter: "A" | "B" | null; type: ShotType;
  origin: "automatic" | "reviewed"; confidence: number; contactImage: Point | null;
  playerPosition: Point | null; opponentPosition: Point | null;
  wall: ShotImpact | null; landing: ShotImpact | null; notes: string;
}
export interface WallCalibration { points: Point[]; tinHeightM: number }
export interface ShotReviewDocument { version: number; reportRevision: number; shots: ReviewShot[]; wallCalibration: WallCalibration | null }
export const SHOT_TYPES: Array<[ShotType, string]> = [["unknown", "Choose shot type"], ["drive", "Drive"], ["crosscourt", "Crosscourt"], ["drop", "Drop"], ["boast", "Boast"], ["lob", "Lob"]];
export const imagePoint = (c: PlaybackContact): Point | null => c.ballImagePosition && c.imageWidth && c.imageHeight ? [c.ballImagePosition[0] / c.imageWidth, c.ballImagePosition[1] / c.imageHeight] : null;

export function automaticShots(data: PlaybackTimeline | null, calibration: WallCalibration | null = null): ReviewShot[] {
  if (!data) return [];
  const contacts = data.contacts.filter(c => c.proxyTimestampUs !== null).sort((a,b) => a.proxyTimestampUs! - b.proxyTimestampUs!);
  const rackets = contacts.filter(c => c.kind === "racket");
  return rackets.map((c,index) => {
    const next = rackets[index+1]?.proxyTimestampUs ?? Infinity;
    const linked = contacts.filter(s => (s.shotContactId === c.id || s.shotContactId == null) && s.proxyTimestampUs! > c.proxyTimestampUs! && s.proxyTimestampUs! < next);
    const wall = linked.find(s => s.kind === "front_wall");
    const landing = linked.find(s => s.kind === "floor");
    const opponent = c.hitter ? data.playerSamples.filter(p => p.playerId !== c.hitter && p.proxyTimestampUs !== null && p.position !== null && Math.abs(p.proxyTimestampUs - c.proxyTimestampUs!) <= 80_000).sort((a,b) => Math.abs(a.proxyTimestampUs! - c.proxyTimestampUs!) - Math.abs(b.proxyTimestampUs! - c.proxyTimestampUs!))[0] : null;
    return { id: c.id, contactUs: c.proxyTimestampUs!, hitter: c.hitter, type: "unknown", origin: "automatic", confidence: Math.min(c.confidence, landing?.confidence ?? 1),
      contactImage: imagePoint(c), playerPosition: c.playerPosition, opponentPosition: opponent?.position ?? null,
      wall: wall ? { timeUs: wall.proxyTimestampUs!, image: imagePoint(wall), position: calibration && imagePoint(wall) ? projectWall(calibration,imagePoint(wall)!) : wall.wallPosition ?? null } : null,
      landing: landing ? { timeUs: landing.proxyTimestampUs!, image: imagePoint(landing), position: landing.floorPosition } : null, notes: "" };
  });
}

export function mergeShots(automatic: ReviewShot[], reviewed: ReviewShot[]): ReviewShot[] {
  const merged = new Map(automatic.map(s => [s.id,s]));
  reviewed.forEach(s => merged.set(s.id,s));
  return [...merged.values()].sort((a,b) => a.contactUs-b.contactUs || a.id.localeCompare(b.id));
}

export function shotSpeed(shot: ReviewShot, nextUs: number | null, timeline: PlaybackTimeline | null) {
  // Only outgoing flight before the first surface contact; never call it launch speed.
  const end = Math.min(shot.wall?.timeUs ?? Infinity, shot.landing?.timeUs ?? Infinity, nextUs ?? Infinity, shot.contactUs + 2_000_000);
  const rows = (timeline?.ballSpeeds ?? []).filter(s => s.proxyTimestampUs !== null && s.proxyEndTimestampUs !== null && s.proxyTimestampUs - (s.timestampUs-s.intervalStartUs) >= shot.contactUs && s.proxyTimestampUs < end);
  const seconds = rows.reduce((sum,s) => sum + Math.max(0,Math.min(end,s.proxyEndTimestampUs!)-s.proxyTimestampUs!)/1e6, 0);
  const values = rows.map(s=>s.speedMps).sort((a,b)=>a-b);
  return { value: values.length >= 3 ? (values[Math.floor((values.length-1)/2)] + values[Math.floor(values.length/2)])/2 : null, seconds, coverage: end > shot.contactUs ? Math.min(1, seconds*1e6/(end-shot.contactUs)) : 0 };
}
