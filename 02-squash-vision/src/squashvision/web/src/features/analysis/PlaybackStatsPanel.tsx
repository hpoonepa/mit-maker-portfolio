import { useId, useState } from "react";
import type { KeyboardEvent } from "react";
import type { PlaybackSnapshot, PlaybackTimeline } from "./playback-model";
import type { ReviewShot } from "./shot-model";
import { formatMatchTime } from "./analysis-model";
import "./PlaybackStatsPanel.css";

interface PlaybackStatsPanelProps {
  shots: ReviewShot[];
  data: PlaybackTimeline | null;
  snapshot: PlaybackSnapshot | null;
  currentTimeUs: number;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  onSeek: (timestampUs: number) => void;
  tinHeightM?: number;
}

function landingLabel(shot: ReviewShot): string {
  const [x, y] = shot.landing!.position!;
  return `Estimated floor landing at ${formatMatchTime(shot.landing!.timeUs, true)}, Player ${shot.hitter}, X ${x.toFixed(2)} m · Y ${y.toFixed(2)} m`;
}

export function PlaybackStatsPanel({ shots, data, snapshot, currentTimeUs, loading, error, onRetry, onSeek, tinHeightM=.48 }: PlaybackStatsPanelProps) {
  const titleId = useId();
  const [view,setView]=useState<"wall"|"landing">("wall");
  const played=shots.filter(shot=>shot.contactUs<=currentTimeUs);
  const wallView=view==="wall";
  const height=wallView?457:975;

  return <section className="playback-stats" aria-labelledby={titleId}>
    <header className="playback-stats__heading"><h2 id={titleId}>On court</h2><span className="playback-stats__clock">{formatMatchTime(currentTimeUs, true)}</span></header>
    <dl className="playback-stats__metrics">
      {(["A", "B"] as const).map((id) => {
        const player = snapshot?.players.find((p) => p.playerId === id);
        return <div key={id} data-player={id}><dt><span>{id}</span> Movement</dt><dd data-testid={`live-distance-${id}`}>{player?.distanceM === null || player?.distanceM === undefined ? "—" : player.distanceM.toFixed(1)}<small>m</small></dd></div>;
      })}
      <div title="Smoothed 2D estimate. Blank when tracking is unavailable."><dt>2D ball speed</dt><dd data-testid="live-ball-speed">{snapshot?.speedMps === null || snapshot?.speedMps === undefined ? "—" : snapshot.speedMps.toFixed(1)}<small>m/s</small></dd></div>
    </dl>
    <div className="playback-stats__court-wrap">
      <div className="playback-stats__map-switch" role="group" aria-label="Shot map view">
        <button type="button" aria-pressed={wallView} onClick={()=>setView("wall")}>Front wall</button>
        <button type="button" aria-pressed={!wallView} onClick={()=>setView("landing")}>Floor bounces</button>
      </div>
      <div className="playback-stats__courts">
        {(["A", "B"] as const).map((id) => {
          const playerShots=played.filter(shot=>shot.hitter===id);
          const positioned=playerShots.filter(shot=>shot[view]?.position && shot[view]!.timeUs<=currentTimeUs);
          return <section key={id} className="playback-stats__player-court" data-court-player={id} aria-label={`Player ${id} ${wallView?"wall impacts":"landings"}`}>
          <header className="playback-stats__court-heading"><h3>Player {id}</h3><span className="playback-stats__shot-total">{playerShots.length} {playerShots.length===1?"shot":"shots"}</span></header>
          <svg className="playback-stats__court" viewBox={`-25 -55 690 ${height+95}`} role="group" aria-label={`Player ${id} ${wallView?"front-wall impacts":"ball landings"}`}>
            <title>Player {id} {wallView?"front-wall impacts":"ball landings"}</title>
            <desc>{wallView?"Front-wall impact positions; vertical position is height above the floor.":"Measured first-bounce positions; volleys and unmeasured bounces have no floor marker."} Positions and player assignments use the same shot records as the scores.</desc>
            <rect className="playback-stats__floor" x="0" y="0" width="640" height={height} />
            {wallView?<><rect className="playback-stats__tin" x="0" y={457-tinHeightM*100} width="640" height={tinHeightM*100}/><path className="playback-stats__lines" d={`M0 279H640 M0 ${457-tinHeightM*100}H640`}/></>:<path className="playback-stats__lines" d="M0 546.5H640 M320 546.5V975 M0 546.5H162.5V711.5H0 M640 546.5H477.5V711.5H640" />}
            <text x="320" y="-24" textAnchor="middle">Front wall</text><text x="320" y={height+35} textAnchor="middle">{wallView?"Floor":"Back"}</text>
            {positioned.map((shot) => {
              const impact=shot[view]!;
              const [x, y] = impact.position!;
              const py=wallView?457-y*100:y*100;
              const label=wallView?`Front-wall impact at ${formatMatchTime(impact.timeUs,true)}, Player ${shot.hitter}, X ${x.toFixed(2)} m · Height ${y.toFixed(2)} m`:landingLabel(shot);
              const seek = () => onSeek(impact.timeUs);
              const handleKey = (event: KeyboardEvent<SVGGElement>) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                seek();
              };
              return <g key={shot.id} role="button" tabIndex={0} aria-label={label} onClick={seek} onKeyDown={handleKey} className={wallView?"playback-stats__wall-impact":"playback-stats__landing"} data-shot-id={shot.id}>
                <title>{label} · Shot {shots.indexOf(shot)+1} · {shot.origin === "reviewed" ? "Video-reviewed marker" : "Tracked estimate"}</title>
                <circle className="playback-stats__hit-target" cx={x * 100} cy={py} r="44" />
                <circle cx={x * 100} cy={py} r="16" />
              </g>;
            })}
          </svg>
          <p className="playback-stats__coverage">{positioned.length} of {playerShots.length} shots plotted</p>
        </section>})}
      </div>
      {!wallView&&<p className="playback-stats__map-note">Volleys and unmeasured bounces have no floor marker.</p>}
      {loading ? <p className="playback-stats__state" role="status">Loading court…</p> : error ? <p className="playback-stats__state" role="status">Court data unavailable <button type="button" onClick={onRetry}>Retry</button></p> : data !== null && !data.calibrationAvailable ? <p className="playback-stats__state">Court calibration required</p> : null}
    </div>
  </section>;
}
