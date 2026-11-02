import { EvidenceLink, UnavailableReport } from "./ReportPrimitives";
import { availability, metricValue, nestedRecord, numberValue, reportSection } from "./report-model";
import type { ReportViewProps } from "./report-model";

interface ComparisonRow {
  label: string;
  near: number | null;
  far: number | null;
  unit?: string;
  nearSample?: number | null;
  farSample?: number | null;
}

function formatValue(value: number | null, row: ComparisonRow, sample: number | null | undefined): string {
  if (value === null) return "Unavailable";
  const measured = row.unit === "m" ? `${value.toFixed(1)} m` : String(value);
  return sample === undefined ? measured : `${measured} · sample ${sample ?? "unavailable"}`;
}

function formatDelta(row: ComparisonRow): string {
  if (row.near === null || row.far === null) return "Unavailable";
  const delta = row.near - row.far;
  const value = row.unit === "m" ? `${Math.abs(delta).toFixed(1)} m` : String(Math.abs(delta));
  return `${delta > 0 ? "+" : delta < 0 ? "−" : ""}${value}`;
}

export function HeadToHeadReport({ report, onSeekEvidence }: ReportViewProps) {
  const section = reportSection(report, "head_to_head");
  if (section === null) return <UnavailableReport title="Head-to-head" reason="not_published" />;
  const state = availability(section.payload);
  if (!state.available) return <UnavailableReport title="Head-to-head" reason={state.reason} />;
  const near = nestedRecord(section.payload, "near");
  const far = nestedRecord(section.payload, "far");
  if (near === null || far === null) return <UnavailableReport title="Head-to-head" reason="insufficient_sample" />;
  const nearMovementPayload = nestedRecord(near, "movement");
  const farMovementPayload = nestedRecord(far, "movement");
  const nearMovement = nearMovementPayload === null ? { available: false, value: null, reason: "not_published" } : metricValue(nearMovementPayload, "distance_m");
  const farMovement = farMovementPayload === null ? { available: false, value: null, reason: "not_published" } : metricValue(farMovementPayload, "distance_m");
  const nearMovementSample = nearMovementPayload === null ? null : numberValue(nearMovementPayload, "sample_count");
  const farMovementSample = farMovementPayload === null ? null : numberValue(farMovementPayload, "sample_count");
  const rows: ComparisonRow[] = [
    { label: "Shots", near: numberValue(near, "shots"), far: numberValue(far, "shots") },
    { label: "Volleys", near: numberValue(near, "volleys"), far: numberValue(far, "volleys") },
    { label: "Winners", near: numberValue(near, "winners"), far: numberValue(far, "winners") },
    { label: "Reviewed errors", near: numberValue(near, "errors"), far: numberValue(far, "errors") },
    { label: "Movement", near: nearMovement.available ? nearMovement.value : null, far: farMovement.available ? farMovement.value : null, unit: "m", nearSample: nearMovementSample, farSample: farMovementSample },
  ];
  const evidenceId = section.evidenceIds[0] ?? null;

  return (
    <section className="report-view" aria-labelledby="head-to-head-title">
      <header className="report-heading"><h2 id="head-to-head-title">Head-to-head</h2></header>
      <div className="report-table-wrap"><table className="report-table comparison-table"><thead><tr><th>Measure</th><th><span className="player-a-mark">A</span> Player A</th><th>Measured delta A−B</th><th><span className="player-b-mark">B</span> Player B</th></tr></thead><tbody>{rows.map((row) => <tr key={row.label}><th>{row.label}</th><td>{formatValue(row.near, row, row.nearSample)}</td><td className="comparison-delta">{formatDelta(row)}</td><td>{formatValue(row.far, row, row.farSample)}</td></tr>)}</tbody></table></div>
      <p className="report-footnote">Differences show Player A minus Player B. A dash means data is unavailable.</p>
      {evidenceId === null ? null : <EvidenceLink evidenceId={evidenceId} label="Seek head-to-head evidence" onSeek={onSeekEvidence} />}
    </section>
  );
}
