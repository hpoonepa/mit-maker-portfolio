import { EvidenceLink, UnavailableReport } from "./ReportPrimitives";
import { arrayValue, availability, booleanValue, numberValue, recordValue, reportSection, stringArrayValue, stringValue } from "./report-model";
import type { ReportViewProps } from "./report-model";

interface ErrorRow {
  id: string;
  category: string;
  status: string;
  counted: boolean;
  side: string | null;
  rallyId: string | null;
  evidenceIds: string[];
}

function errorRows(payload: Record<string, unknown>): ErrorRow[] {
  const rows: ErrorRow[] = [];
  for (const candidate of arrayValue(payload, "items").slice(0, 2_000)) {
    const value = recordValue(candidate);
    if (value === null) continue;
    const id = stringValue(value, "id");
    const category = stringValue(value, "category");
    const status = stringValue(value, "status");
    const counted = booleanValue(value, "counted");
    if (id === null || category === null || status === null || counted === null) continue;
    rows.push({ id, category, status, counted, side: stringValue(value, "side"), rallyId: stringValue(value, "rally_id"), evidenceIds: stringArrayValue(value, "evidence_ids") });
  }
  return rows;
}

export function ErrorsReport({ report, onSeekEvidence }: ReportViewProps) {
  const section = reportSection(report, "errors");
  if (section === null) return <UnavailableReport title="Errors" reason="not_published" />;
  const state = availability(section.payload);
  if (!state.available) return <UnavailableReport title="Errors" reason={state.reason} />;
  const objectiveCount = numberValue(section.payload, "objective_count");
  const subjectiveCount = numberValue(section.payload, "reviewed_subjective_count");
  const pendingCount = numberValue(section.payload, "unreviewed_candidate_count");
  const rows = errorRows(section.payload);
  if (objectiveCount === null && subjectiveCount === null && pendingCount === null && rows.length === 0) return <UnavailableReport title="Errors" reason="insufficient_sample" />;
  const confirmed = rows.filter((row) => row.status === "accepted" && row.counted);
  const needsReview = rows.filter((row) => row.status === "pending" || row.status === "unreviewed");
  const rejected = rows.filter((row) => row.status === "rejected");
  const confirmedCount = objectiveCount !== null && subjectiveCount !== null ? objectiveCount + subjectiveCount : null;
  const groups = [
    { key: "confirmed", label: "Confirmed errors", count: confirmedCount, rows: confirmed, detail: "Confirmed errors included in the report." },
    { key: "review", label: "Needs review", count: pendingCount, rows: needsReview, detail: "These possible errors need review before they count." },
    { key: "rejected", label: "Rejected errors", count: rows.length === 0 ? null : rejected.length, rows: rejected, detail: "Rejected errors are kept for reference and excluded from the count." },
  ];

  return (
    <section className="report-view" aria-labelledby="errors-title">
      <header className="report-heading"><h2 id="errors-title">Errors</h2></header>
      <div className="error-groups">
        {groups.map((group) => <section key={group.key} className={`error-group error-group-${group.key}`} aria-label={group.label}>
          <header><div><p className="eyebrow">{group.label}</p><h3>{group.count ?? "Unavailable"}</h3></div><p>{group.detail}</p></header>
          {group.rows.length === 0 ? <p className="report-footnote">No individual error details are available.</p> : <ol>
            {group.rows.map((row) => <li key={row.id}>
              <div><strong>{row.id}</strong><span>{row.category} · {row.status}</span></div>
              <dl><div><dt>Counted</dt><dd>{row.counted ? "Counted" : "Not counted"}</dd></div><div><dt>Side</dt><dd>{row.side ?? "Unavailable"}</dd></div><div><dt>Rally</dt><dd>{row.rallyId ?? "Unavailable"}</dd></div></dl>
              {row.evidenceIds.length === 0 ? <span className="report-footnote">Evidence unavailable</span> : group.key === "review"
                ? <EvidenceLink evidenceId={row.evidenceIds[0] ?? null} label={`Review evidence ${row.id}`} onSeek={onSeekEvidence} />
                : <div className="evidence-row">{row.evidenceIds.map((id) => <EvidenceLink key={id} evidenceId={id} label={`Open evidence ${id}`} onSeek={onSeekEvidence} />)}</div>}
            </li>)}
          </ol>}
        </section>)}
      </div>
    </section>
  );
}
