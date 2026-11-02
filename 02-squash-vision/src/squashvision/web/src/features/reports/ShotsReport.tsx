import { useMemo, useState } from "react";

import { EvidenceLink, UnavailableReport } from "./ReportPrimitives";
import { availability, nestedRecord, numberValue, recordValue, reportSection, stringValue } from "./report-model";
import type { ReportViewProps } from "./report-model";

const PLAYER_LABEL: Record<string, string> = { near: "Player A", far: "Player B", unknown: "Unknown player" };

interface ShotRow {
  player: string;
  metric: string;
  count: number | null;
  share: number | null;
  category: "type" | "outcome" | "side" | "volley";
  evidenceId: string | null;
}

function aggregateEntry(value: unknown): { count: number | null; share: number | null; evidenceId: string | null } {
  if (typeof value === "number" && Number.isFinite(value)) return { count: value, share: null, evidenceId: null };
  const record = recordValue(value);
  return record === null
    ? { count: null, share: null, evidenceId: null }
    : { count: numberValue(record, "count"), share: numberValue(record, "share"), evidenceId: stringValue(record, "representative_event_id") };
}

function aggregateRows(payload: Record<string, unknown>): ShotRow[] {
  const players = nestedRecord(payload, "players");
  if (players === null) return [];
  const rows: ShotRow[] = [];
  for (const [player, candidate] of Object.entries(players)) {
    const summary = recordValue(candidate);
    if (summary === null) continue;
    const playerCount = numberValue(summary, "count");
    const types = nestedRecord(summary, "types") ?? {};
    for (const [kind, typeCandidate] of Object.entries(types)) {
      const type = recordValue(typeCandidate);
      if (type === null) continue;
      rows.push({ player, metric: kind, count: numberValue(type, "count"), share: numberValue(type, "share"), category: "type", evidenceId: stringValue(type, "representative_event_id") });
    }
    const outcomes = nestedRecord(summary, "outcomes") ?? {};
    for (const [outcome, candidateCount] of Object.entries(outcomes)) {
      const parsed = aggregateEntry(candidateCount);
      rows.push({ player, metric: outcome, count: parsed.count, share: parsed.share, category: "outcome", evidenceId: parsed.evidenceId });
    }
    const sides = nestedRecord(summary, "sides") ?? {};
    for (const [side, candidateCount] of Object.entries(sides)) {
      const parsed = aggregateEntry(candidateCount);
      rows.push({ player, metric: side, count: parsed.count, share: parsed.share, category: "side", evidenceId: parsed.evidenceId });
    }
    if (playerCount !== null && playerCount > 0) {
      rows.push({ player, metric: "Volley count", count: numberValue(summary, "volleys"), share: null, category: "volley", evidenceId: stringValue(summary, "volley_representative_event_id") });
    }
  }
  return rows;
}

export function ShotsReport({ report, onSeekEvidence }: ReportViewProps) {
  const section = reportSection(report, "shots");
  const [playerFilter, setPlayerFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [sideFilter, setSideFilter] = useState("all");
  const [outcomeFilter, setOutcomeFilter] = useState("all");
  const rows = useMemo(() => section === null ? [] : aggregateRows(section.payload), [section]);
  if (section === null) return <UnavailableReport title="Shots" reason="not_published" />;
  const state = availability(section.payload);
  if (!state.available) return <UnavailableReport title="Shots" reason={state.reason} />;
  const complete = stringValue(section.payload, "aggregate_contract") === "complete";
  const players = nestedRecord(section.payload, "players");
  const unknown = players === null ? null : nestedRecord(players, "unknown");
  const unknownCount = unknown === null ? null : numberValue(unknown, "count");
  const totalCount = numberValue(section.payload, "total_count");
  const coverage = totalCount !== null && totalCount > 0 && unknownCount !== null
    ? Math.max(0, Math.min(1, (totalCount - unknownCount) / totalCount))
    : null;
  const typeOptions = [...new Set(rows.filter((row) => row.category === "type").map((row) => row.metric))];
  const sideOptions = [...new Set(rows.filter((row) => row.category === "side").map((row) => row.metric))];
  const outcomeOptions = [...new Set(rows.filter((row) => row.category === "outcome").map((row) => row.metric))];
  const visibleRows = rows.filter((row) =>
    (playerFilter === "all" || row.player === playerFilter)
    && (
      sideFilter !== "all"
        ? row.category === "side" && row.metric === sideFilter
        : (row.category !== "type" || typeFilter === "all" || row.metric === typeFilter)
          && (row.category !== "outcome" || outcomeFilter === "all" || row.metric === outcomeFilter)
    ),
  );
  const dimensions = [
    { category: "type" as const, label: "Primary type" },
    { category: "outcome" as const, label: "Outcome" },
    { category: "side" as const, label: "Side" },
    { category: "volley" as const, label: "Volley flag" },
  ];

  return (
    <section className="report-view shots-report" aria-labelledby="shots-title">
      <header className="report-heading"><h2 id="shots-title">Shots</h2></header>
      <div className="shot-coverage" role="status" aria-label="Shot classification coverage">
        <strong>Classification coverage</strong>
        {coverage === null || unknownCount === null || totalCount === null
          ? <span>Unknown-player coverage was not published.</span>
          : <><span>{Math.round(coverage * 100)}% classified to a player</span><span>{unknownCount} unknown of {totalCount} shots</span><meter min="0" max="1" value={coverage} aria-label="Player classification coverage" /></>}
      </div>
      <div className="report-filters" role="group" aria-label="Shot filters">
        <label>Player<select value={playerFilter} onChange={(event) => setPlayerFilter(event.currentTarget.value)}><option value="all">All players</option><option value="near">Player A</option><option value="far">Player B</option><option value="unknown">Unknown</option></select></label>
        <label>Primary type<select value={typeFilter} disabled={sideFilter !== "all"} onChange={(event) => setTypeFilter(event.currentTarget.value)}><option value="all">All primary types</option>{typeOptions.map((value) => <option key={value}>{value}</option>)}</select></label>
        <label>Side<select value={sideFilter} disabled={sideOptions.length === 0} onChange={(event) => setSideFilter(event.currentTarget.value)}><option value="all">{sideOptions.length === 0 ? "Side unavailable in report" : "All sides"}</option>{sideOptions.map((value) => <option key={value}>{value}</option>)}</select></label>
        <label>Outcome<select value={outcomeFilter} disabled={sideFilter !== "all"} onChange={(event) => setOutcomeFilter(event.currentTarget.value)}><option value="all">All outcomes</option>{outcomeOptions.map((value) => <option key={value}>{value}</option>)}</select></label>
      </div>
      {!complete ? <div className="status-neutral" role="status">Complete aggregate contract unavailable; published values remain visible but are not marked available.</div> : null}
      <div className="shot-dimensions">
        {dimensions.map(({ category, label }) => {
          const categoryRows = visibleRows.filter((row) => row.category === category);
          if (categoryRows.length === 0 && sideFilter !== "all") return null;
          return <section key={category} className="shot-dimension" aria-label={label}>
            <header><h3>{label}</h3><span>{categoryRows.length} results</span></header>
            {categoryRows.length === 0 ? <p className="report-footnote">No {label.toLowerCase()} results match these filters.</p> : <div className="report-table-wrap"><table className="report-table"><thead><tr><th>Player</th><th>Measure</th><th>Count</th><th>Measured share</th><th>Evidence</th></tr></thead><tbody>
              {categoryRows.map((row) => <tr key={`${row.player}-${row.category}-${row.metric}`} aria-label={row.category === "volley" ? `Independent volley flag count ${row.count ?? "unavailable"} for ${row.player}` : undefined}><th>{PLAYER_LABEL[row.player] ?? row.player}</th><td>{row.category === "type" ? `Primary type: ${row.metric}` : row.category === "side" ? `Side: ${row.metric}` : row.metric}</td><td>{row.count ?? "Unavailable"}</td><td>{row.share === null ? "Not published" : <span className="shot-share"><meter min="0" max="1" value={row.share} aria-label={`${PLAYER_LABEL[row.player] ?? row.player} ${row.metric} share`} /><span>{Math.round(row.share * 100)}%</span></span>}</td><td><EvidenceLink evidenceId={row.evidenceId ?? section.evidenceIds[0] ?? null} label={`Seek ${PLAYER_LABEL[row.player] ?? row.player} ${row.metric}`} onSeek={onSeekEvidence} /></td></tr>)}
            </tbody></table></div>}
          </section>;
        })}
      </div>
      <p className="report-footnote">Volleys are counted separately from shot type. A dash means volley data is unavailable.</p>
    </section>
  );
}
