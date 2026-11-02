import { useId, useMemo, useState } from "react";
import type { components } from "../../api/types.generated";
import "./RallyCourtRead.css";

type ShotDetail = components["schemas"]["ShotDetail"];
type ShotKind = components["schemas"]["ShotKind"];
type ShotOutcomeKind = components["schemas"]["ShotOutcomeKind"];
type Hitter = "near" | "far" | null;

export interface RallyCourtReadRally {
  id: string;
  ordinal: number;
  startUs: number | null;
  endUs: number | null;
  timingAvailable: boolean;
  outcome: ShotOutcomeKind | null;
  reviewStatus: string | null;
  sourceEvidenceIds: string[];
  representativeEventId?: string | null;
}

export interface RallyCourtReadProps {
  rally: RallyCourtReadRally;
  shots: ShotDetail[];
  selectedShotId?: string | null;
  representativeEventId?: string | null;
  onPlayEvidence?: (evidenceId: string) => void;
  onSeekShot: (evidenceOrShotId: string) => void;
}

const COURT_WIDTH_M = 6.4;
const COURT_LENGTH_M = 9.75;
const VIEWBOX_WIDTH = 640;
const VIEWBOX_HEIGHT = 975;
const PLAYER_STYLE: Record<string, { color: string; shape: "circle" | "square" }> = {
  near: { color: "#7bc4ea", shape: "circle" },
  far: { color: "#ef997b", shape: "square" },
};

export function mapCourtPoint(contact: readonly [number, number]): { x: number; y: number } {
  return {
    x: (contact[0] / COURT_WIDTH_M) * VIEWBOX_WIDTH,
    y: (contact[1] / COURT_LENGTH_M) * VIEWBOX_HEIGHT,
  };
}

export function buildContactPath(shots: readonly Pick<ShotDetail, "id" | "contact">[]): string[][] {
  const paths: string[][] = [];
  let current: string[] = [];
  for (const shot of shots) {
    if (shot.contact === null) {
      if (current.length > 0) paths.push(current);
      current = [];
      continue;
    }
    current.push(shot.id);
  }
  if (current.length > 0) paths.push(current);
  return paths;
}

function formatDuration(rally: RallyCourtReadRally): string {
  if (!rally.timingAvailable || rally.startUs === null || rally.endUs === null) return "Timing unavailable";
  return `${Math.max(0, (rally.endUs - rally.startUs) / 1_000_000).toFixed(1)} s`;
}
function formatTimestamp(timestampUs: number | null): string {
  if (timestampUs === null) return "—";
  const totalMs = Math.max(0, Math.round(timestampUs / 1_000));
  const minutes = Math.floor(totalMs / 60_000);
  const seconds = Math.floor((totalMs % 60_000) / 1_000);
  const milliseconds = totalMs % 1_000;
  return `${minutes}:${String(seconds).padStart(2, "0")}.${String(milliseconds).padStart(3, "0")}`;
}

function label(value: string): string {
  return value.replaceAll("_", " ").toUpperCase();
}

function shotAriaLabel(shot: ShotDetail, index: number): string {
  const hitter = shot.hitter === "near" ? "Player A" : shot.hitter === "far" ? "Player B" : "Unknown player";
  return `Shot ${index + 1}, ${hitter}, ${label(shot.shotKind)}, ${label(shot.outcome)}${shot.isVolley ? ", volley" : ""}`;
}

export function RallyCourtRead({ rally, shots, selectedShotId = null, representativeEventId = null, onSeekShot, onPlayEvidence }: RallyCourtReadProps) {
  const titleId = useId();
  const descriptionId = useId();
  const arrowId = useId().replaceAll(":", "");
  const [localSelectedShotId, setLocalSelectedShotId] = useState<string | null>(selectedShotId);
  const selected = selectedShotId ?? localSelectedShotId;
  const orderedShots = shots;
  const paths = useMemo(() => buildContactPath(orderedShots), [orderedShots]);
  const positioned = orderedShots.filter((shot) => shot.contact !== null);
  const terminal = orderedShots[orderedShots.length - 1] ?? null;
  const terminalLabel = terminal === null
    ? "Shot unavailable"
    : `${terminal.hitter === "near" ? "A" : terminal.hitter === "far" ? "B" : "?"} · ${label(terminal.shotKind)}`;
  const headline = rally.outcome === null ? terminalLabel : `${label(rally.outcome)} · ${terminalLabel}`;
  const playEvidenceId = representativeEventId ?? rally.representativeEventId ?? rally.sourceEvidenceIds[0] ?? null;
  const timingLabel = rally.timingAvailable ? `${formatTimestamp(rally.startUs)}–${formatTimestamp(rally.endUs)}` : "Timing unavailable";
  const seek = (shot: ShotDetail): void => {
    setLocalSelectedShotId(shot.id);
    onSeekShot(shot.sourceEvidenceIds[0] ?? shot.id);
  };

  return (
    <article className="rally-court-read" aria-labelledby={titleId}>
      <header className="rally-court-read__header">
        <div>
          <p className="rally-court-read__eyebrow">Rally {rally.ordinal}</p>
          <h2 id={titleId}>{headline}</h2>
          <p className="rally-court-read__disclaimer">Contact path—not ball flight{rally.outcome === null ? " · Outcome unavailable" : ""}</p>
        </div>
        <dl className="rally-court-read__stats">
          <div><dt>Duration</dt><dd>{formatDuration(rally)}</dd></div>
          <div><dt>Shots</dt><dd>{shots.length} {shots.length === 1 ? "shot" : "shots"}</dd></div>
          <div><dt>Coverage</dt><dd>{shots.length === 0 ? "Unavailable" : `${positioned.length}/${shots.length}`}</dd></div>
        </dl>
        <button type="button" className="rally-court-read__play" disabled={playEvidenceId === null} onClick={() => { if (playEvidenceId !== null) (onPlayEvidence ?? onSeekShot)(playEvidenceId); }}>
          <span>Play Rally {rally.ordinal} evidence</span><small>{playEvidenceId === null ? "Evidence unavailable" : timingLabel}</small>
        </button>
      </header>

      <div className="rally-court-read__body">
        <div className="rally-court-read__court-wrap">
          {positioned.length === 0 ? <div className="rally-court-read__unavailable" role="status"><strong>Court contact path unavailable</strong><span>Shot details are available below.</span></div> : null}
          <svg className="rally-court-read__court" viewBox="0 0 640 975" role="img" aria-labelledby={`${titleId} ${descriptionId}`}>
            <title id={descriptionId}>Top-down court contact path for rally {rally.ordinal}</title>
            <desc>Numbered measured contact points are connected only when consecutive shots have known calibrated contacts. This is a contact path, not continuous ball flight.</desc>
            <defs>
              <marker id={arrowId} markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto" markerUnits="strokeWidth">
                <path className="rally-court-read__arrowhead" d="M0,0 L9,4.5 L0,9 Z" />
              </marker>
            </defs>
            <rect className="rally-court-read__surface" x="0" y="0" width="640" height="975" />
            <rect className="rally-court-read__outline" x="2" y="2" width="636" height="971" />
            <line className="rally-court-read__line" x1="0" y1="487.5" x2="640" y2="487.5" />
            <line className="rally-court-read__line rally-court-read__service" x1="0" y1="650" x2="640" y2="650" />
            <text className="rally-court-read__orientation" x="320" y="40" textAnchor="middle">Front wall</text>
            <text className="rally-court-read__orientation" x="320" y="945" textAnchor="middle">Back court</text>
            {paths.flatMap((path) => {
              const points = path.map((id) => orderedShots.find((shot) => shot.id === id)).filter((shot): shot is ShotDetail => shot !== undefined && shot.contact !== null).map((shot) => mapCourtPoint(shot.contact!));
              return points.slice(1).map((point, index) => {
                const previous = points[index];
                return <polyline key={`${path.join("-")}-${index}`} className="rally-court-read__path" markerEnd={`url(#${arrowId})`} points={`${previous.x},${previous.y} ${point.x},${point.y}`} />;
              });
            })}
            {orderedShots.map((shot, index) => {
              if (shot.contact === null) return null;
              const point = mapCourtPoint(shot.contact);
              const player = PLAYER_STYLE[shot.hitter ?? ""];
              const isSelected = selected === shot.id;
              return (
                <g key={shot.id} className={`rally-court-read__point ${isSelected ? "is-selected" : ""}`}>
                  <title>{shotAriaLabel(shot, index)}</title>
                  <g
                    className="rally-court-read__hit-target"
                    role="button"
                    tabIndex={0}
                    aria-label={shotAriaLabel(shot, index)}
                    onClick={() => seek(shot)}
                    onKeyDown={(event) => {
                      if (event.key !== "Enter" && event.key !== " ") return;
                      event.preventDefault();
                      seek(shot);
                    }}
                  >
                    <circle cx={point.x} cy={point.y} r="48" />
                  </g>
                  {player?.shape === "square" ? <rect className="rally-court-read__marker" x={point.x - 22} y={point.y - 22} width="44" height="44" style={{ fill: player.color }} /> : <circle className="rally-court-read__marker" cx={point.x} cy={point.y} r="22" style={{ fill: player?.color ?? "#f2eee5" }} />}
                  <text className="rally-court-read__number" x={point.x} y={point.y + 6} textAnchor="middle">{index + 1}</text>
                </g>
              );
            })}
          </svg>
        </div>

        <div className="rally-court-read__sequence">
          <p className="rally-court-read__eyebrow">Shot sequence</p>
          <ol aria-label="Accessible shot sequence">
            {orderedShots.length === 0 ? <li>Shot sequence unavailable.</li> : orderedShots.map((shot, index) => (
              <li key={shot.id}>
                <button type="button" className={`rally-court-read__shot ${selected === shot.id ? "is-selected" : ""}`} aria-label={shotAriaLabel(shot, index)} onClick={() => seek(shot)}>
                  <span className="rally-court-read__shot-number">{index + 1}</span>
                  <span><strong>{shot.hitter === "near" ? "A" : shot.hitter === "far" ? "B" : "?"} · {label(shot.shotKind)}</strong><small>{shot.contact === null ? "Contact unavailable" : "Positioned contact"} · {label(shot.outcome)}{shot.isVolley ? " · VOLLEY" : ""}</small></span>
                </button>
              </li>
            ))}
          </ol>
          <dl className="rally-court-read__provenance">
            <div><dt>Positioned coverage</dt><dd>{shots.length === 0 ? "Unavailable" : `${positioned.length} of ${shots.length} contacts`}</dd></div>
            <div><dt>Review</dt><dd>{rally.reviewStatus === null ? "Unavailable" : label(rally.reviewStatus)}</dd></div>
            <div><dt>Provenance</dt><dd>{rally.sourceEvidenceIds.length > 0 ? "Evidence linked" : "Evidence unavailable"}</dd></div>
          </dl>
        </div>
      </div>
    </article>
  );
}
