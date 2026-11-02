import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import type { components } from "../../api/types.generated";
import { IncompletePageError, allShotPages } from "../analysis/analysis-data";
import { RallyCourtRead } from "../analysis/RallyCourtRead";
import { UnavailableReport } from "./ReportPrimitives";
import { arrayValue, availability, booleanValue, numberValue, recordValue, reportSection, stringArrayValue, stringValue } from "./report-model";
import type { ReportViewProps } from "./report-model";

type ShotDetail = components["schemas"]["ShotDetail"];
type ShotOutcome = components["schemas"]["ShotOutcomeKind"];

interface RalliesReportProps extends ReportViewProps {
  matchId: string;
  durationUs: number;
}

interface RallyRow {
  id: string;
  ordinal: number;
  startUs: number | null;
  endUs: number | null;
  timingAvailable: boolean;
  shotIds: string[];
  reviewStatus: string | null;
  evidenceIds: string[];
  outcome: ShotOutcome | null;
  representativeEventId: string | null;
}

const SHOT_OUTCOMES: Record<string, true> = { unknown: true, in_play: true, winner: true, error: true, stroke: true, let: true };

function parseRows(payload: Record<string, unknown>): RallyRow[] {
  const rows: RallyRow[] = [];
  for (const candidate of arrayValue(payload, "items")) {
    const value = recordValue(candidate);
    if (value === null) continue;
    const id = stringValue(value, "prediction_id") ?? stringValue(value, "id");
    const ordinal = numberValue(value, "ordinal");
    if (id === null || ordinal === null) continue;
    const rawOutcome = stringValue(value, "outcome");
    rows.push({
      id,
      ordinal,
      startUs: numberValue(value, "start_timestamp_us") ?? numberValue(value, "startUs"),
      endUs: numberValue(value, "end_timestamp_us") ?? numberValue(value, "endUs"),
      timingAvailable: booleanValue(value, "timing_available") ?? booleanValue(value, "timingAvailable") ?? false,
      shotIds: stringArrayValue(value, "shot_ids").length > 0 ? stringArrayValue(value, "shot_ids") : stringArrayValue(value, "shotIds"),
      reviewStatus: stringValue(value, "review_status") ?? stringValue(value, "reviewStatus"),
      evidenceIds: stringArrayValue(value, "source_evidence_ids").length > 0 ? stringArrayValue(value, "source_evidence_ids") : stringArrayValue(value, "sourceEvidenceIds"),
      outcome: rawOutcome !== null && SHOT_OUTCOMES[rawOutcome] === true ? rawOutcome as ShotOutcome : null,
      representativeEventId: stringValue(value, "representative_event_id"),
    });
  }
  return rows.sort((left, right) => left.ordinal - right.ordinal || (left.startUs ?? Number.MAX_SAFE_INTEGER) - (right.startUs ?? Number.MAX_SAFE_INTEGER));
}

export function RalliesReport({ report, matchId, durationUs, onSeekEvidence }: RalliesReportProps) {
  const section = reportSection(report, "rallies");
  const rows = useMemo(() => section === null ? [] : parseRows(section.payload), [section]);
  const [selectedRallyId, setSelectedRallyId] = useState<string | null>(null);
  const state = section === null ? { available: false, reason: "not_published" } : availability(section.payload);
  const shots = useQuery({
    queryKey: ["matches", matchId, "shots", report.revision],
    enabled: state.available && rows.length > 0 && matchId !== "",
    retry: false,
    queryFn: ({ signal }) => allShotPages(matchId, report.revision, report.predictionRevision, durationUs, signal),
  });
  if (section === null) return <UnavailableReport title="Rallies" reason="not_published" />;
  if (!state.available) return <UnavailableReport title="Rallies" reason={state.reason} />;
  if (rows.length === 0) return <UnavailableReport title="Rallies" reason="insufficient_sample" />;

  const partialShots = shots.error instanceof IncompletePageError ? shots.error.items as ShotDetail[] : [];
  const loadedShots = shots.data ?? partialShots;
  const shotsById = new Map(loadedShots.map((shot) => [shot.id, shot]));
  const selectedRow = rows.find((row) => row.id === selectedRallyId) ?? rows[0];
  const selectedShots = selectedRow.shotIds.map((shotId) => shotsById.get(shotId)).filter((shot): shot is ShotDetail => shot !== undefined && shot.rallyId === selectedRow.id);
  const missing = selectedRow.shotIds.length - selectedShots.length;

  return (
    <section className="report-view rallies-report" aria-labelledby="rallies-title">
      <header className="report-heading"><h2 id="rallies-title">Rallies</h2><p>{rows.length} {rows.length === 1 ? "rally" : "rallies"} · revision {report.revision}</p></header>
      {shots.isPending ? <p className="status-neutral" role="status">Loading shots…</p> : null}
      {shots.isError ? <div className="status-error" role="alert"><strong>Shot evidence incomplete</strong><p>Some shots could not be loaded. {partialShots.length} {partialShots.length === 1 ? "shot was" : "shots were"} retained.</p><button type="button" disabled={shots.isFetching} onClick={() => void shots.refetch()}>{shots.isFetching ? "Retrying shot evidence…" : "Retry shot evidence"}</button></div> : null}
      <div className="rally-live-layout">
        <div className="rally-index" role="tablist" aria-label="Rally index">
          {rows.map((row) => {
            const duration = row.timingAvailable && row.startUs !== null && row.endUs !== null ? `${Math.max(0, (row.endUs - row.startUs) / 1_000_000).toFixed(1)} s` : "Timing unavailable";
            return (
              <button
                key={row.id}
                id={`rally-tab-${row.id}`}
                type="button"
                role="tab"
                aria-selected={selectedRow.id === row.id}
                aria-controls={`rally-panel-${row.id}`}
                tabIndex={selectedRow.id === row.id ? 0 : -1}
                onClick={() => setSelectedRallyId(row.id)}
              >
                <span><strong>Rally {row.ordinal}</strong><small>{duration}</small></span>
                <span>{row.outcome === null ? "Outcome unavailable" : row.outcome.replaceAll("_", " ")}</span>
                <span>{row.shotIds.length} {row.shotIds.length === 1 ? "shot" : "shots"}</span>
              </button>
            );
          })}
        </div>
        <div id={`rally-panel-${selectedRow.id}`} className="rally-live-detail" role="tabpanel" aria-labelledby={`rally-tab-${selectedRow.id}`}>
          {missing > 0 && !shots.isPending ? <p className="rally-data-state" role="status">{missing} {missing === 1 ? "shot" : "shots"} unavailable for Rally {selectedRow.ordinal}. The court view shows only available positions.</p> : null}
          <RallyCourtRead
            rally={{ id: selectedRow.id, ordinal: selectedRow.ordinal, startUs: selectedRow.startUs, endUs: selectedRow.endUs, timingAvailable: selectedRow.timingAvailable, outcome: selectedRow.outcome, reviewStatus: selectedRow.reviewStatus, sourceEvidenceIds: selectedRow.evidenceIds }}
            shots={selectedShots}
            representativeEventId={selectedRow.representativeEventId}
            onSeekShot={onSeekEvidence}
            onPlayEvidence={onSeekEvidence}
          />
        </div>
      </div>
    </section>
  );
}
