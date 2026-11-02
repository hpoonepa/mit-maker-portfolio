import { EvidenceLink, UnavailableReport } from "./ReportPrimitives";
import { arrayValue, availability, numberValue, readableReason, recordValue, reportSection, stringArrayValue, stringValue } from "./report-model";
import type { ReportViewProps } from "./report-model";

function measuredValue(value: number | null): string {
  if (value === null) return "Unavailable";
  return value >= 0 && value <= 1 ? `${(value * 100).toFixed(1)}%` : value.toFixed(2);
}

export function CoachingReport({ report, onSeekEvidence }: ReportViewProps) {
  const section = reportSection(report, "coaching");
  if (section === null) return <UnavailableReport title="Coaching" reason="not_published" />;
  const state = availability(section.payload);
  if (!state.available) return <UnavailableReport title="Coaching" reason={state.reason} />;
  const findings = arrayValue(section.payload, "findings").slice(0, 100).map(recordValue).filter((value): value is Record<string, unknown> => value !== null);
  if (findings.length === 0) return <UnavailableReport title="Coaching" reason="insufficient_sample" />;

  return (
    <section className="report-view" aria-labelledby="coaching-title">
      <header className="report-heading"><h2 id="coaching-title">Coaching</h2></header>
      <ol className="coaching-ledger">
        {findings.map((finding, index) => {
          const rule = stringValue(finding, "rule") ?? `finding_${index + 1}`;
          const subject = stringValue(finding, "subject") ?? "subject unavailable";
          const measured = numberValue(finding, "measured");
          const baseline = numberValue(finding, "baseline");
          const threshold = numberValue(finding, "threshold");
          const comparator = stringValue(finding, "comparator");
          const sample = numberValue(finding, "sample_count");
          const evidence = stringValue(finding, "evidence");
          const links = stringArrayValue(finding, "supporting_event_ids");
          const complete = measured !== null
            && comparator !== null
            && sample !== null
            && (threshold !== null || baseline !== null);
          if (!complete) {
            return <li key={`${rule}-${subject}-${index}`} className="coaching-unavailable">
              <header><span className="eyebrow">{readableReason(rule)} · {subject}</span><strong>Finding incomplete</strong></header>
              <p>This finding needs a measured value, comparison, sample count, and threshold or baseline.</p>
            </li>;
          }
          return (
            <li key={`${rule}-${subject}-${index}`}>
              <header><span className="eyebrow">{readableReason(rule)} · {subject}</span><strong>Measured finding</strong></header>
              <dl>
                <div><dt>Measured value</dt><dd>{measuredValue(measured)}</dd></div>
                <div><dt>Comparator</dt><dd>{comparator === null ? "Unavailable" : readableReason(comparator)}</dd></div>
                <div><dt>Baseline</dt><dd>{measuredValue(baseline)}</dd></div>
                <div><dt>Threshold</dt><dd>{measuredValue(threshold)}</dd></div>
                <div><dt>Sample count</dt><dd>{sample === null ? "Unavailable" : `Sample ${sample}`}</dd></div>
              </dl>
              <p>{evidence ?? "Supporting detail is unavailable."}</p>
              <div className="evidence-row">{links.length === 0 ? <span>No supporting video links</span> : links.map((id) => <EvidenceLink key={id} evidenceId={id} label={`Seek supporting shot ${id}`} onSeek={onSeekEvidence} />)}</div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
