import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, RefObject } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";

import type { components } from "../../api/types.generated";
import { request } from "../../api/client";

type PlayerObservation = components["schemas"]["PlayerObservationDetail"];
type BallObservation = components["schemas"]["BallObservationDetail"];
type TimelineItem = components["schemas"]["TimelineItem"];

interface VideoOverlayProps {
  matchId: string;
  currentTimeUs: number;
  playing: boolean;
  videoRef?: RefObject<HTMLVideoElement | null>;
  players: PlayerObservation[];
  balls: BallObservation[];
  controlsContainer?: HTMLElement | null;
  sourceWidth?: number;
  sourceHeight?: number;
  selectedEvent?: TimelineItem | null;
}

interface OverlayToggles {
  playerA: boolean;
  playerB: boolean;
  pose: boolean;
  boxes: boolean;
  ball: boolean;
  trajectory: boolean;
  uncertainty: boolean;
}

interface ContainTransform {
  scale: number;
  offsetX: number;
  offsetY: number;
}

const DEFAULT_TOGGLES: OverlayToggles = {
  playerA: true,
  playerB: true,
  pose: true,
  boxes: false,
  ball: true,
  trajectory: false,
  uncertainty: false,
};

const PLAYER_COLOR: Record<string, string> = {
  near: "#7bc4ea",
  far: "#ef997b",
};
const BALL_COLOR = "#e3d78b";

export function computeContainTransform(sourceWidth: number, sourceHeight: number, width: number, height: number): ContainTransform {
  const scale = Math.min(width / Math.max(1, sourceWidth), height / Math.max(1, sourceHeight));
  const rawOffsetX = (width - sourceWidth * scale) / 2;
  const rawOffsetY = (height - sourceHeight * scale) / 2;
  return {
    scale,
    offsetX: Math.abs(rawOffsetX) < Number.EPSILON * Math.max(1, width) ? 0 : rawOffsetX,
    offsetY: Math.abs(rawOffsetY) < Number.EPSILON * Math.max(1, height) ? 0 : rawOffsetY,
  };
}
export function covarianceEllipse(covariance: BallObservation["covariance"]): { radiusX: number; radiusY: number; rotation: number } | null {
  if (covariance === null) return null;
  const xx = covariance[0][0];
  const xy = (covariance[0][1] + covariance[1][0]) / 2;
  const yy = covariance[1][1];
  const discriminant = Math.sqrt(Math.max(0, ((xx - yy) / 2) ** 2 + xy ** 2));
  const major = Math.max(0, (xx + yy) / 2 + discriminant);
  const minor = Math.max(0, (xx + yy) / 2 - discriminant);
  return {
    radiusX: Math.max(4, Math.min(120, Math.sqrt(major) * 2)),
    radiusY: Math.max(4, Math.min(120, Math.sqrt(minor) * 2)),
    rotation: 0.5 * Math.atan2(2 * xy, xx - yy),
  };
}

const TOGGLE_NAMES = Object.keys(DEFAULT_TOGGLES) as Array<keyof OverlayToggles>;
const LEGACY_DEFAULTS = { playerA: true, playerB: true, pose: false, ball: true, trajectory: true, uncertainty: true };

function persistedOverrides(matchId: string): Partial<OverlayToggles> {
  try {
    const stored = sessionStorage.getItem(`mosaic:overlay:v2:${matchId}`);
    const legacy = stored === null;
    const candidate: unknown = JSON.parse(stored ?? sessionStorage.getItem(`mosaic:overlay:${matchId}`) ?? "null");
    if (typeof candidate !== "object" || candidate === null || Array.isArray(candidate)) return {};
    const values = !legacy && "version" in candidate && candidate.version === 2 && "overrides" in candidate ? candidate.overrides : legacy ? candidate : null;
    if (typeof values !== "object" || values === null || Array.isArray(values)) return {};
    const overrides: Partial<OverlayToggles> = {};
    for (const name of TOGGLE_NAMES) {
      const value = (values as Record<string, unknown>)[name];
      if (typeof value !== "boolean") continue;
      // Old storage wrote defaults automatically; only departures prove a choice.
      if (legacy && (!(name in LEGACY_DEFAULTS) || value === LEGACY_DEFAULTS[name as keyof typeof LEGACY_DEFAULTS])) continue;
      overrides[name] = value;
    }
    return overrides;
  } catch {
    return {};
  }
}


function lowerBound(items: readonly BallObservation[], timestampUs: number): number {
  let low = 0;
  let high = items.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if ((items[middle]?.timestampUs ?? Number.MAX_SAFE_INTEGER) < timestampUs) low = middle + 1;
    else high = middle;
  }
  return low;
}

export function hasBallPosition(item: BallObservation): boolean {
  return item.visible && item.x !== null && item.y !== null && Number.isFinite(item.x) && Number.isFinite(item.y);
}

export function isConfidentBall(item: BallObservation): boolean {
  return hasBallPosition(item) && item.evidence === "observed" && !item.ambiguous && item.probability >= 0.5
    && item.sourceTimestampUs === item.timestampUs && item.sourceFrameIndex !== null;
}

export function ballTrailWindow(ordered: readonly BallObservation[], currentTimeUs: number): BallObservation[] {
  return ordered.slice(lowerBound(ordered, currentTimeUs - 250_000), lowerBound(ordered, currentTimeUs + 1));
}

export function ballTrailSegments(ordered: readonly BallObservation[]): Array<readonly [BallObservation, BallObservation]> {
  const segments: Array<readonly [BallObservation, BallObservation]> = [];
  for (let index = 1; index < ordered.length; index += 1) {
    const previous = ordered[index - 1];
    const next = ordered[index];
    if (isConfidentBall(previous) && isConfidentBall(next) && previous.segmentId !== null && previous.segmentId === next.segmentId
      && next.timestampUs > previous.timestampUs && next.timestampUs - previous.timestampUs <= 50_000) segments.push([previous, next]);
  }
  return segments;
}

export function ballAtSourceFrame(ordered: readonly BallObservation[], timestampUs: number, frameIndex: number): BallObservation | null {
  const index = lowerBound(ordered, timestampUs);
  const item = ordered[index];
  if (item === undefined || item.timestampUs !== timestampUs) return null;
  if (item.evidence === "observed" && item.sourceFrameIndex !== frameIndex) return null;
  return item;
}

export interface SourceFrame {
  proxyTimestampUs: number;
  sourceTimestampUs: number;
  sourceFrameIndex: number;
}

interface FrameMapPage { startUs: number; endUs: number; items: SourceFrame[] }

function decodeFrameMap(value: unknown): FrameMapPage {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new TypeError("Frame map is invalid");
  const page = value as Record<string, unknown>;
  if (!Number.isSafeInteger(page.startUs) || !Number.isSafeInteger(page.endUs) || !Array.isArray(page.items)) throw new TypeError("Frame map is invalid");
  let previous = -1;
  for (const candidate of page.items) {
    if (typeof candidate !== "object" || candidate === null || Array.isArray(candidate)) throw new TypeError("Frame map entry is invalid");
    const item = candidate as Record<string, unknown>;
    for (const name of ["proxyTimestampUs", "sourceTimestampUs", "sourceFrameIndex"]) {
      if (!Number.isSafeInteger(item[name]) || (item[name] as number) < 0) throw new TypeError("Frame map entry is invalid");
    }
    if ((item.proxyTimestampUs as number) <= previous) throw new TypeError("Frame map is not ordered");
    previous = item.proxyTimestampUs as number;
  }
  return value as FrameMapPage;
}

export function sourceFrameAt(ordered: readonly SourceFrame[], timeUs: number, exactPresentation: boolean): SourceFrame | null {
  let low = 0;
  let high = ordered.length;
  const roundingUs = exactPresentation ? 1_000 : 0;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (ordered[middle].proxyTimestampUs <= timeUs + roundingUs) low = middle + 1; else high = middle;
  }
  const frame = ordered[low - 1];
  if (frame === undefined) return null;
  const ageUs = timeUs - frame.proxyTimestampUs;
  // Presented frames tolerate only timestamp rounding. Without browser frame
  // callbacks, use the preceding proxy frame for at most one 30fps interval.
  return exactPresentation ? Math.abs(ageUs) <= roundingUs ? frame : null : ageUs >= 0 && ageUs < 34_000 ? frame : null;
}

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() =>
    typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = (): void => setReduced(media.matches);
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, []);
  return reduced;
}

export function VideoOverlay({ matchId, currentTimeUs, playing, videoRef, players, balls, controlsContainer = null, sourceWidth, sourceHeight }: VideoOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [preferences, setPreferences] = useState(() => ({ matchId, overrides: persistedOverrides(matchId) }));
  const overrides = preferences.matchId === matchId ? preferences.overrides : persistedOverrides(matchId);
  const toggles = { ...DEFAULT_TOGGLES, ...overrides };
  const [sizeVersion, setSizeVersion] = useState(0);
  const [visible, setVisible] = useState(true);
  const reducedMotion = useReducedMotion();
  const [frameClock, setFrameClock] = useState({ timeUs: currentTimeUs, exact: false });
  const [seeking, setSeeking] = useState(false);
  const presentationTimeUs = videoRef?.current == null ? currentTimeUs : frameClock.timeUs;
  const windowAnchorUs = Math.floor(presentationTimeUs / 10_000_000) * 10_000_000;
  const startUs = Math.max(0, windowAnchorUs - 10_000_000);
  const endUs = windowAnchorUs + 20_000_000;
  const frameMap = useQuery({
    queryKey: ["matches", matchId, "frame-map", startUs, endUs],
    queryFn: ({ signal }) => request("/api/v1/matches/{match_id}/media/frame-map", "get", { path: { match_id: matchId }, query: { startUs, endUs }, signal, decode: decodeFrameMap }),
    staleTime: 60_000,
    placeholderData: (previous, query) => query?.queryKey[1] === matchId ? previous : undefined,
  });
  const sourceFrame = seeking ? null : sourceFrameAt(frameMap.data?.items ?? [], presentationTimeUs, frameClock.exact);

  useEffect(() => {
    if (videoRef?.current?.requestVideoFrameCallback === undefined) setFrameClock({ timeUs: currentTimeUs, exact: false });
  }, [currentTimeUs, videoRef]);
  useEffect(() => {
    if (preferences.matchId !== matchId) setPreferences({ matchId, overrides: persistedOverrides(matchId) });
  }, [matchId, preferences.matchId]);
  useEffect(() => {
    const video = videoRef?.current;
    if (video == null || !visible) return;
    let frameId = 0;
    let active = true;
    const hasVideoFrames = typeof video.requestVideoFrameCallback === "function";
    const beginSeek = (): void => setSeeking(true);
    const endSeek = (): void => {
      if (!hasVideoFrames) { setFrameClock({ timeUs: Math.round(video.currentTime * 1_000_000), exact: false }); setSeeking(false); }
    };
    video.addEventListener("seeking", beginSeek);
    video.addEventListener("seeked", endSeek);
    if (hasVideoFrames) {
      const update = (_now: number, metadata: VideoFrameCallbackMetadata): void => {
        if (!active) return;
        setFrameClock({ timeUs: Math.round(metadata.mediaTime * 1_000_000), exact: true });
        setSeeking(false);
        frameId = video.requestVideoFrameCallback(update);
      };
      // Keep the subscription while paused: a seek also presents a new frame.
      frameId = video.requestVideoFrameCallback(update);
    } else if (playing && !reducedMotion) {
      const update = (): void => {
        if (!active) return;
        setFrameClock({ timeUs: Math.round(video.currentTime * 1_000_000), exact: false });
        frameId = requestAnimationFrame(update);
      };
      frameId = requestAnimationFrame(update);
    }
    return () => {
      active = false;
      video.removeEventListener("seeking", beginSeek);
      video.removeEventListener("seeked", endSeek);
      if (hasVideoFrames) video.cancelVideoFrameCallback(frameId); else cancelAnimationFrame(frameId);
    };
  }, [matchId, playing, reducedMotion, videoRef, visible]);

  const currentPlayers = useMemo(() => {
    const slots: Record<string, PlayerObservation> = {};
    if (sourceFrame === null) return slots;
    for (const item of players) {
      if (item.timestampUs !== sourceFrame.sourceTimestampUs || (item.evidence === "observed" && item.sourceFrameIndex !== sourceFrame.sourceFrameIndex)) continue;
      const slot = item.playerId === "A" ? "near" : item.playerId === "B" ? "far" : item.playerId;
      slots[slot] = item;
    }
    return slots;
  }, [sourceFrame?.sourceTimestampUs, sourceFrame?.sourceFrameIndex, players]);
  const orderedBalls = useMemo(() => [...balls].sort((left, right) => left.timestampUs - right.timestampUs), [balls]);
  const currentBall = useMemo(() => sourceFrame === null ? null : ballAtSourceFrame(orderedBalls, sourceFrame.sourceTimestampUs, sourceFrame.sourceFrameIndex), [sourceFrame?.sourceTimestampUs, sourceFrame?.sourceFrameIndex, orderedBalls]);
  const trail = useMemo(() => sourceFrame === null ? [] : ballTrailWindow(orderedBalls, sourceFrame.sourceTimestampUs), [sourceFrame?.sourceTimestampUs, orderedBalls]);
  const intrinsicWidth = sourceWidth !== undefined && sourceWidth > 0 ? sourceWidth : currentBall?.sourceWidth ?? 1920;
  const intrinsicHeight = sourceHeight !== undefined && sourceHeight > 0 ? sourceHeight : currentBall?.sourceHeight ?? 1080;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas === null || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setSizeVersion((version) => version + 1));
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas === null || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry?.isIntersecting ?? true));
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

  const draw = useCallback((): void => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (canvas === null || canvas === undefined || context === null || context === undefined) return;
    const bounds = canvas.getBoundingClientRect();
    const width = Math.max(1, bounds.width || intrinsicWidth);
    const height = Math.max(1, bounds.height || intrinsicHeight);
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    const pixelWidth = Math.round(width * dpr);
    const pixelHeight = Math.round(height * dpr);
    if (canvas.width !== pixelWidth) canvas.width = pixelWidth;
    if (canvas.height !== pixelHeight) canvas.height = pixelHeight;
    context.clearRect(0, 0, pixelWidth, pixelHeight);
    context.save();
    context.scale(dpr, dpr);
    const transform = computeContainTransform(intrinsicWidth, intrinsicHeight, width, height);
    context.translate(transform.offsetX, transform.offsetY);
    context.scale(transform.scale, transform.scale);
    context.lineWidth = Math.max(2, 3 / transform.scale);
    context.font = `${Math.max(14, 16 / transform.scale)}px Inter Tight`;

    for (const [slot, item] of Object.entries(currentPlayers)) {
      const enabled = slot === "near" ? toggles.playerA : slot === "far" ? toggles.playerB : false;
      if (!enabled) continue;
      const color = PLAYER_COLOR[slot] ?? "#f3f6ef";
      context.strokeStyle = color;
      context.fillStyle = color;
      if (toggles.boxes) {
        context.setLineDash(item.ambiguous ? [8, 5] : []);
        context.beginPath();
        context.rect(item.box[0], item.box[1], item.box[2] - item.box[0], item.box[3] - item.box[1]);
        context.stroke();
      }
      if (toggles.pose) {
        context.lineWidth = 2 / transform.scale;
        context.setLineDash(item.evidence === "observed" ? [] : [8, 5]);
        for (const [startIndex, endIndex] of item.skeletonEdges) {
          const start = item.keypoints[startIndex];
          const end = item.keypoints[endIndex];
          if (start === undefined || end === undefined || start.confidence < 0.25 || end.confidence < 0.25) continue;
          context.beginPath();
          context.moveTo(start.x, start.y);
          context.lineTo(end.x, end.y);
          context.stroke();
        }
      }
    }

    if (toggles.ball && currentBall !== null) {
      context.strokeStyle = BALL_COLOR;
      context.fillStyle = BALL_COLOR;
      context.setLineDash([]);
      context.lineWidth = 1.5 / transform.scale;
      if (isConfidentBall(currentBall)) {
        if (toggles.trajectory && !reducedMotion) {
          for (const [previous, next] of ballTrailSegments(trail)) {
            context.beginPath();
            context.moveTo(previous.x!, previous.y!);
            context.lineTo(next.x!, next.y!);
            context.stroke();
          }
        }
        context.beginPath();
        context.arc(currentBall.x!, currentBall.y!, 3 / transform.scale, 0, Math.PI * 2);
        context.fill();
      }
      if (toggles.uncertainty && hasBallPosition(currentBall)) {
        const ellipse = covarianceEllipse(currentBall.covariance);
        if (ellipse !== null) {
          context.setLineDash([3 / transform.scale, 3 / transform.scale]);
          context.beginPath();
          context.ellipse(currentBall.x!, currentBall.y!, ellipse.radiusX, ellipse.radiusY, ellipse.rotation, 0, Math.PI * 2);
          context.stroke();
        }
      }
    }
    context.restore();
  }, [currentBall, currentPlayers, intrinsicHeight, intrinsicWidth, reducedMotion, sizeVersion, toggles, trail]);

  useEffect(() => {
    if (!visible) return;
    draw();
  }, [draw, visible]);

  const updateToggle = (event: ChangeEvent<HTMLInputElement>): void => {
    const name = event.currentTarget.name as keyof OverlayToggles;
    const checked = event.currentTarget.checked;
    const next = { ...overrides, [name]: checked };
    setPreferences({ matchId, overrides: next });
    try {
      sessionStorage.setItem(`mosaic:overlay:v2:${matchId}`, JSON.stringify({ version: 2, overrides: next }));
    } catch { /* Overlay choices work without session storage. */ }
  };

  const evidenceState = (item: PlayerObservation): string => item.ambiguous
    ? "uncertain"
    : item.evidence === "observed" ? "observed" : "estimated";
  const selectedText = [
    currentPlayers.near === undefined ? "Player A unavailable" : `Player A ${evidenceState(currentPlayers.near)}`,
    currentPlayers.far === undefined ? "Player B unavailable" : `Player B ${evidenceState(currentPlayers.far)}`,
    frameMap.isError ? "Frame alignment unavailable" : currentBall === null
      ? "Ball unavailable at this frame"
      : !hasBallPosition(currentBall) ? "Ball not visible at this frame" : currentBall.ambiguous
        ? `Ball uncertainty · ${(currentBall.ambiguityReason ?? "uncertain position").replaceAll("_", " ")} · ambiguous`
        : currentBall.evidence === "observed"
          ? isConfidentBall(currentBall) ? "Ball observed" : "Ball low confidence · marker hidden"
          : "Ball reconstructed · estimated · marker hidden",
  ].filter((value): value is string => value !== null);
  const controls = (
    <>
    <output className="sr-only" aria-live={playing ? "off" : "polite"}>{selectedText.join(". ")}</output>
    <details className="overlay-settings">
      <summary>Overlay options</summary>
      <div className="overlay-legend" aria-label="Overlay legend"><span data-kind="player-a">Player A</span><span data-kind="player-b">Player B</span><span data-kind="ball">Ball</span><span data-kind="ambiguous">Estimated / ambiguous</span></div>
      <fieldset className="overlay-toggles">
        <legend>Evidence overlay</legend>
        {([
          ["playerA", "Player A"],
          ["playerB", "Player B"],
          ["pose", "Skeleton"],
          ["boxes", "Boxes"],
          ["ball", "Ball"],
          ["trajectory", "Short trail"],
          ["uncertainty", "Uncertainty"],
        ] as Array<[keyof OverlayToggles, string]>).map(([name, label]) => (
          <label key={name}><input type="checkbox" name={name} aria-label={label} checked={toggles[name]} onChange={updateToggle} />{label}</label>
        ))}
      </fieldset>
      <p className="overlay-source-details">{intrinsicWidth} × {intrinsicHeight} source{toggles.pose ? " · Pose landmarks visible" : ""}</p>
    </details>
    </>
  );

  return (
    <>
      <div className="video-overlay" data-source-size={`${intrinsicWidth}x${intrinsicHeight}`}>
        <canvas ref={canvasRef} aria-hidden="true" />
      </div>
      {controlsContainer === null ? controls : createPortal(controls, controlsContainer)}
    </>
  );
}
