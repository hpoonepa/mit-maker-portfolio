import type { CSSProperties } from "react";

import { EvidenceLink, UnavailableReport } from "./ReportPrimitives";
import { arrayValue, availability, metricValue, nestedRecord, numberValue, reportSection, readableReason } from "./report-model";
import type { ReportViewProps } from "./report-model";

interface HeatCell {
  row: number;
  column: number;
  count: number;
}

function heatCells(heatmap: Record<string, unknown>): { cells: HeatCell[]; rows: number; columns: number; maximum: number } {
  const rows = numberValue(heatmap, "rows") ?? 0;
  const columns = numberValue(heatmap, "columns") ?? 0;
  const cells: HeatCell[] = [];
  let maximum = 0;
  for (const [row, candidate] of arrayValue(heatmap, "counts").slice(0, rows).entries()) {
    if (!Array.isArray(candidate)) continue;
    for (const [column, count] of candidate.slice(0, columns).entries()) {
      if (typeof count !== "number" || !Number.isFinite(count) || count < 0) continue;
      cells.push({ row, column, count });
      maximum = Math.max(maximum, count);
    }
  }
  return { cells, rows, columns, maximum };
}

export function MovementReport({ report, onSeekEvidence }: ReportViewProps) {
  const section = reportSection(report, "movement");
  if (section === null) return <UnavailableReport title="Movement" reason="not_published" />;
  const state = availability(section.payload);
  const calibrationRevision = numberValue(section.payload, "active_calibration_revision") ?? numberValue(section.payload, "activeCalibrationRevision");
  const heatmap = nestedRecord(section.payload, "heatmap");
  if (!state.available || calibrationRevision === null) return <UnavailableReport title="Movement" reason={state.reason ?? "missing_calibration"} />;
  const grid = heatmap === null ? { cells: [], rows: 0, columns: 0, maximum: 0 } : heatCells(heatmap);
  const measuredPositions = grid.cells.reduce((total, cell) => total + cell.count, 0);
  const plotReady = heatmap !== null && grid.rows > 0 && grid.columns > 0 && grid.cells.length > 0 && measuredPositions > 0 && grid.maximum > 0;
  const distance = metricValue(section.payload, "distance_m");
  const recovery = nestedRecord(section.payload, "t_recovery");
  const medianRecovery = recovery === null ? { available: false, value: null, reason: "not_published" } : metricValue(recovery, "median_seconds");
  const recoverySamples = recovery === null ? null : numberValue(recovery, "sample_count");
  const excluded = heatmap === null ? {} : nestedRecord(heatmap, "excluded") ?? {};
  const exclusions = Object.entries(excluded).filter((entry): entry is [string, number] => typeof entry[1] === "number" && Number.isFinite(entry[1]));
  const excludedTotal = exclusions.reduce((total, [, count]) => total + count, 0);
  const evidenceId = section.evidenceIds[0] ?? null;

  return (
    <section className="report-view" aria-labelledby="movement-title">
      <header className="report-heading"><p className="eyebrow">Calibration revision {calibrationRevision}</p><h2 id="movement-title">Movement</h2></header>
      <div className="movement-layout">
        {plotReady ? <svg className="movement-heatmap" viewBox="0 0 640 975" role="img" aria-label="Court movement heatmap for Player A and Player B">
          <title>Court movement heatmap for Player A and Player B</title>
          <rect className="heatmap-court" x="1" y="1" width="638" height="973" />
          <line className="heatmap-court" x1="0" y1="487.5" x2="640" y2="487.5" />
          {grid.cells.map((cell) => <rect key={`${cell.row}-${cell.column}`} className="heat-cell" x={(cell.column / grid.columns) * 640} y={(cell.row / grid.rows) * 975} width={640 / grid.columns} height={975 / grid.rows} style={{ "--heat-opacity": Math.max(0.08, cell.count / grid.maximum) } as CSSProperties}><title>{cell.count} measured positions</title></rect>)}
          <text x="18" y="42">Player A / B positions</text>
        </svg> : <div className="report-inline-unavailable movement-empty"><strong>Heatmap unavailable</strong><p>{heatmap === null ? "Heatmap data is unavailable." : "No measured court positions are available."} Calibration revision {calibrationRevision} remains active.</p></div>}
        <dl className="movement-ledger">
          <div><dt>Player labels</dt><dd><span className="player-a-mark">A</span>Player A <span className="player-b-mark">B</span>Player B</dd></div>
          <div><dt>Position sample</dt><dd>{measuredPositions} measured positions</dd></div>
          <div><dt>Distance</dt><dd>{distance.available && distance.value !== null ? `${distance.value.toFixed(1)} m` : `Unavailable · ${readableReason(distance.reason)}`}</dd></div>
          <div><dt>T recovery</dt><dd>{medianRecovery.available && medianRecovery.value !== null ? `${medianRecovery.value.toFixed(2)} s · sample ${recoverySamples ?? "unavailable"}` : `Unavailable · ${readableReason(medianRecovery.reason)}${recoverySamples === null ? " · sample not published" : ` · sample ${recoverySamples}`}`}</dd></div>
          <div><dt>Excluded positions</dt><dd>{exclusions.length === 0 ? "No exclusions published" : `${excludedTotal} excluded · ${exclusions.map(([reason, count]) => `${count} ${readableReason(reason)}`).join("; ")}`}</dd></div>
        </dl>
      </div>
      {evidenceId === null ? null : <EvidenceLink evidenceId={evidenceId} label="Seek movement evidence" onSeek={onSeekEvidence} />}
    </section>
  );
}
