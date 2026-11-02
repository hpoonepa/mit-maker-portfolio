import { useQuery } from "@tanstack/react-query";
import { memo, useId, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { request } from "../../api/client";
import { formatMatchTime } from "./analysis-model";
import { decodeTrackingStats } from "./tracking-stats";
import type { TrackingContact, TrackingStats } from "./tracking-stats";
import "./TrackingStatsPanel.css";

interface TrackingStatsPanelProps {
  matchId: string;
  reportRevision: number;
  onSeekVideo: (proxyTimestampUs: number) => void;
}

const PAGE_SIZE = 25;
type PlayerFilter = "all" | "A" | "B" | "unknown";
const percent = (value: number): string => `${Math.round(value * 100)}%`;
const playerName = (hitter: TrackingContact["hitter"]): string => hitter === null ? "Unknown hitter" : `Player ${hitter}`;
const readable = (value: string): string => value.replaceAll("_", " ");

export function MatchSummary(props: TrackingStatsPanelProps) {
  const [opened, setOpened] = useState(false);
  return <details className="match-summary" onToggle={(event) => { if (event.currentTarget.open) setOpened(true); }}><summary>Match summary</summary>{opened ? <TrackingStatsPanel {...props} /> : null}</details>;
}

export const TrackingStatsPanel = memo(function TrackingStatsPanel({ matchId, reportRevision, onSeekVideo }: TrackingStatsPanelProps) {
  const stats = useQuery({
    queryKey: ["matches", matchId, "tracking-stats", reportRevision],
    staleTime: 30_000,
    queryFn: async ({ signal }) => {
      const result = await request("/api/v1/matches/{match_id}/reports/{revision}/tracking-stats", "get", {
        path: { match_id: matchId, revision: reportRevision }, signal, decode: decodeTrackingStats,
      });
      if (result.reportRevision !== reportRevision) throw new Error("Tracking statistics belong to another report revision");
      return result;
    },
  });
  if (stats.isPending) return <section className="tracking-stats" aria-label="Tracking stats"><h2>Tracking stats</h2><p role="status">Loading measurements…</p></section>;
  if (stats.isError) return <section className="tracking-stats" aria-label="Tracking stats"><h2>Tracking stats</h2><p role="status">Measurements unavailable.</p><button type="button" disabled={stats.isFetching} onClick={() => void stats.refetch()}>{stats.isFetching ? "Loading…" : "Retry measurements"}</button></section>;
  return <TrackingStatsView key={`${matchId}:${reportRevision}:${stats.data.calibrationRevision}`} stats={stats.data} matchId={matchId} onSeekVideo={onSeekVideo} />;
});

export function TrackingStatsView({ stats, matchId, onSeekVideo }: { stats: TrackingStats; matchId: string; onSeekVideo: TrackingStatsPanelProps["onSeekVideo"] }) {
  const titleId = useId();
  const [expanded, setExpanded] = useState(false);
  const [filter, setFilter] = useState<PlayerFilter>("all");
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const indexedContacts = useMemo(() => stats.contacts.map((contact, index) => ({ contact, number: index + 1 })), [stats.contacts]);
  const filtered = useMemo(() => indexedContacts.filter(({ contact }) => filter === "all" || (filter === "unknown" ? contact.hitter === null : contact.hitter === filter)), [indexedContacts, filter]);
  const positioned = filtered.filter(({ contact }) => contact.position !== null);
  const visible = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const seek = (contact: TrackingContact): void => {
    if (contact.proxyTimestampUs === null) return;
    setSelectedId(contact.id);
    onSeekVideo(contact.proxyTimestampUs);
  };
  const contactLabel = (contact: TrackingContact, number: number): string => `Contact ${number}, ${playerName(contact.hitter)}, ${formatMatchTime(contact.timestampUs, true)}`;
  const speed = stats.ballSpeed;

  return (
    <section className="tracking-stats" aria-labelledby={titleId}>
      <header className="tracking-stats__heading"><h2 id={titleId}>Tracking stats</h2><span>{formatMatchTime(stats.startUs)}–{formatMatchTime(stats.endUs)}</span></header>
      <dl className="tracking-stats__metrics">
        {(["A", "B"] as const).map((id) => {
          const player = stats.players.find((candidate) => candidate.playerId === id)!;
          return <div key={id} className={`tracking-stats__metric tracking-stats__metric--${id.toLowerCase()}`}><dt><span className="tracking-stats__player">{id}</span>Tracked movement</dt><dd>{player.distanceM === null ? "Unavailable" : <>{player.distanceM.toFixed(1)} <span>m</span></>}</dd><small>{player.distanceM === null ? "No usable calibrated path" : `${player.trackedSeconds.toFixed(1)} s tracked · ${percent(player.coverage)} coverage`}</small></div>;
        })}
        <div className="tracking-stats__metric"><dt>Estimated ball speed</dt><dd>{speed.medianMps === null ? "Unavailable" : <>{speed.medianMps.toFixed(1)} <span>m/s</span></>}</dd><small>{speed.medianMps === null ? "No usable calibrated samples" : `Median · ${(speed.medianMps * 3.6).toFixed(0)} km/h · ${percent(speed.coverage)} coverage`}</small></div>
      </dl>
      <p className="tracking-stats__note">{stats.players.some((player) => !player.identityVerified) ? "Player identity review pending. " : ""}Movement estimates cover tracked portions. Ball speed assumes motion on the floor plane.</p>
      {!stats.calibrationAvailable ? <p className="tracking-stats__unavailable">Court calibration required for metres and speed. <Link to={`/matches/${matchId}/setup`}>Open court setup</Link></p> : null}
      <details className="tracking-stats__details" onToggle={(event) => setExpanded(event.currentTarget.open)}>
        <summary>Contact positions <span>{stats.contacts.filter((contact) => contact.position !== null).length}/{stats.contacts.length} mapped</span></summary>
        {expanded ? <>
          <p className="tracking-stats__note">Player feet at inferred racket contact. X runs left to right; Y runs from the front wall to the back wall. Coordinates are in metres.</p>
          <div className="tracking-stats__filters" role="group" aria-label="Filter contact positions">{(["all", "A", "B", "unknown"] as const).map((value) => <button key={value} type="button" aria-pressed={filter === value} onClick={() => { setFilter(value); setPage(0); }}>{value === "all" ? "All" : value === "unknown" ? "Unknown" : `Player ${value}`}</button>)}</div>
          <div className="tracking-stats__contacts">
            <figure className="tracking-stats__court">
              <svg viewBox="-28 -42 696 1054" role="group" aria-label="Player positions at contact on the court">
                <title>Player positions at contact on the court</title>
                <rect className="tracking-stats__court-floor" x="0" y="0" width="640" height="975" />
                <path className="tracking-stats__court-lines" d="M0 549H640 M320 549V975 M0 549H160V709H0 M640 549H480V709H640" />
                <text x="320" y="-16" textAnchor="middle">Front wall · Y 0</text><text x="320" y="1008" textAnchor="middle">Back wall · Y 9.75</text>
                {positioned.map(({ contact, number }) => {
                  const [x, y] = contact.position!;
                  const marker = <circle cx={x * 100} cy={y * 100} r={selectedId === contact.id ? 13 : 9} />;
                  return <g key={contact.id} className={`tracking-stats__point tracking-stats__point--${contact.hitter?.toLowerCase() ?? "unknown"}${selectedId === contact.id ? " is-selected" : ""}`} role={contact.proxyTimestampUs === null ? undefined : "button"} tabIndex={contact.proxyTimestampUs === null ? undefined : 0} aria-label={contactLabel(contact, number)} onClick={() => seek(contact)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); seek(contact); } }}><title>{contactLabel(contact, number)} · X {x.toFixed(2)}, Y {y.toFixed(2)}</title>{marker}</g>;
                })}
              </svg>
              <figcaption>{positioned.length === 0 ? "No mapped contacts in this selection." : `${positioned.length} mapped ${positioned.length === 1 ? "contact" : "contacts"}`}</figcaption>
            </figure>
            <div className="tracking-stats__table-wrap">
              <table className="tracking-stats__table"><caption>Contact locations and confidence</caption><thead><tr><th scope="col">Video</th><th scope="col">Hitter</th><th scope="col">X / Y (m)</th><th scope="col">Contact</th></tr></thead><tbody>
                {visible.map(({ contact, number }) => <tr key={contact.id} className={selectedId === contact.id ? "is-selected" : undefined}><td><button type="button" aria-label={`Play ${contactLabel(contact, number).toLowerCase()}`} disabled={contact.proxyTimestampUs === null} onClick={() => seek(contact)}>{formatMatchTime(contact.timestampUs, true)}<small>{contact.proxyTimestampUs === null ? "Frame unavailable" : `Contact ${number} ↗`}</small></button></td><td><span className={`tracking-stats__hitter tracking-stats__hitter--${contact.hitter?.toLowerCase() ?? "unknown"}`}>{playerName(contact.hitter)}</span><small>{contact.hitter === null ? "Unassigned" : `${percent(contact.hitterConfidence)} confidence`}</small></td><td>{contact.position === null ? <><span>Unavailable</span><small>{contact.reason === null ? "Position not measured" : readable(contact.reason)}</small></> : `${contact.position[0].toFixed(2)} / ${contact.position[1].toFixed(2)}`}</td><td>{percent(contact.confidence)}<small>{contact.reviewRequired ? "Needs review" : "Estimated"}</small></td></tr>)}
              </tbody></table>
              {filtered.length === 0 ? <p className="tracking-stats__note">No contacts in this selection.</p> : null}
              {pages > 1 ? <nav className="tracking-stats__pages" aria-label="Contact pages"><button type="button" disabled={page === 0} onClick={() => setPage((value) => value - 1)}>Previous</button><span>{page + 1} / {pages}</span><button type="button" disabled={page + 1 >= pages} onClick={() => setPage((value) => value + 1)}>Next</button></nav> : null}
            </div>
          </div>
          <details className="tracking-stats__method">
            <summary>Measurement details</summary>
            <p>{stats.calibrationRevision === null ? "No court calibration." : `Court calibration ${stats.calibrationRevision}.`} Report {stats.reportRevision} · prediction {stats.predictionRevision}.</p>
            {stats.calibrationReason === null ? null : <p>{readable(stats.calibrationReason)}</p>}
            <p>Speed = projected distance ÷ elapsed source-frame time.</p>
            <p>Ball speed: {speed.sampleCount} samples over {speed.trackedSeconds.toFixed(1)} s · {speed.excludedSamples} excluded{speed.p90Mps === null ? "." : ` · 90th percentile ${speed.p90Mps.toFixed(1)} m/s.`}</p>
            {speed.reason === null ? null : <p>{readable(speed.reason)}</p>}
            <ul>{stats.limitations.map((limitation, index) => <li key={index}>{readable(limitation)}</li>)}</ul>
          </details>
        </> : null}
      </details>
    </section>
  );
}
