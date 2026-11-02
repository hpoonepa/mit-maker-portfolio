import type { CSSProperties } from "react";

import { EvidenceLink, MetricLedger, MetricRow, UnavailableReport } from "./ReportPrimitives";
import { availability, metricValue, numberValue, readableReason, reportSection } from "./report-model";
import type { ReportViewProps } from "./report-model";

function seconds(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)} s`;
}

function percentage(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

export function OverviewReport({ report, onSeekEvidence }: ReportViewProps) {
  const section = reportSection(report, "overview");
  if (section === null) return <UnavailableReport title="Overview" reason="not_published" />;
  const state = availability(section.payload);
  if (!state.available) return <UnavailableReport title="Overview" reason={state.reason} />;
  const evidenceId = section.evidenceIds[0] ?? null;
  const rallies = numberValue(section.payload, "rally_count");
  const timedRallies = numberValue(section.payload, "timed_rally_count");
  const shots = numberValue(section.payload, "shot_count");
  const active = numberValue(section.payload, "active_duration_s");
  const rest = numberValue(section.payload, "rest_duration_s");
  const ratio = metricValue(section.payload, "work_rest_ratio");
  const completion = metricValue(section.payload, "review_completion");
  const quality = metricValue(section.payload, "evidence_quality");
  const pulseTotal = active !== null && rest !== null ? active + rest : null;
  const winners = numberValue(section.payload, "winner_count");
  const reviewedErrors = numberValue(section.payload, "reviewed_error_count");
  const averageRally = numberValue(section.payload, "average_rally_s");
  const longestRally = numberValue(section.payload, "longest_rally_s");
  const timedSample = timedRallies === null ? "Timed rally sample unavailable" : `${timedRallies} timed ${timedRallies === 1 ? "rally" : "rallies"}`;
  const shotSample = shots === null ? "Shot sample unavailable" : `${shots} shots`;
  const pulseShares = pulseTotal !== null && pulseTotal > 0 && active !== null && rest !== null ? { active: active / pulseTotal, rest: rest / pulseTotal } : null;

  return (
    <section className="report-view overview-report" aria-labelledby="overview-title">
      <header className="report-heading"><h2 id="overview-title">Match statistics</h2></header>
      <section className="report-metric-group overview-outcomes" aria-labelledby="primary-stats-title" aria-label="Results">
        <h3 id="primary-stats-title">Results</h3>
        <dl className="outcome-row">
          <div><dt>Rallies</dt><dd>{rallies ?? "—"}</dd><small>{timedSample}</small></div>
          <div><dt>Shots</dt><dd>{shots ?? "—"}</dd><small>{shotSample}</small></div>
          <div><dt>Winners</dt><dd>{winners ?? "—"}</dd><small>{winners === null ? "Outcome unavailable" : "Recorded outcomes"}</small></div>
          <div><dt>Errors</dt><dd>{reviewedErrors ?? "—"}</dd><small>{reviewedErrors === null ? "Review sample unavailable" : "Accepted review only"}</small></div>
        </dl>
      </section>
      <section className="report-metric-group" aria-labelledby="performance-stats-title" aria-label="Rally timing">
        <div className="report-group-heading"><h3 id="performance-stats-title">Rally timing</h3><span>{timedSample}</span></div>
        {pulseShares !== null ? <div className="match-pulse" aria-label={`Rally timing: ${seconds(active)} active, ${seconds(rest)} rest`}>
          <span className="pulse-active" style={{ "--pulse-share": `${pulseShares.active * 100}%` } as CSSProperties}>Active · {seconds(active)}</span>
          <span className="pulse-rest" style={{ "--pulse-share": `${pulseShares.rest * 100}%` } as CSSProperties}>Rest · {seconds(rest)}</span>
        </div> : <div className="report-inline-unavailable"><strong>Rally timing unavailable</strong><p>Active and rest durations are needed to show this breakdown.</p></div>}
        <MetricLedger>
          <MetricRow label="Work / rest" value={ratio.available ? ratio.value?.toFixed(2) : "—"} availability={ratio.available ? "Measured ratio" : readableReason(ratio.reason)} sample={timedSample} />
          <MetricRow label="Average rally" value={timedRallies !== null && timedRallies > 0 ? seconds(averageRally) : "—"} availability={averageRally !== null && timedRallies !== null && timedRallies > 0 ? "Measured duration" : "Timed rally sample required"} sample={timedSample} />
          <MetricRow label="Longest rally" value={timedRallies !== null && timedRallies > 0 ? seconds(longestRally) : "—"} availability={longestRally !== null && timedRallies !== null && timedRallies > 0 ? "Measured duration" : "Timed rally sample required"} sample={timedSample} />
        </MetricLedger>
      </section>
      <section className="report-metric-group trust-summary" aria-labelledby="trust-stats-title" aria-label="Analysis quality">
        <h3 id="trust-stats-title">Analysis quality</h3>
        <MetricLedger>
          <MetricRow label="Evidence quality" value={percentage(quality.value)} availability={quality.available ? "Published quality" : readableReason(quality.reason)} sample={`${section.evidenceIds.length} video links`} />
          <MetricRow label="Review completion" value={percentage(completion.value)} availability={completion.available ? "Published completion" : readableReason(completion.reason)} sample={reviewedErrors === null ? "Reviewed error sample unavailable" : `${reviewedErrors} accepted reviewed ${reviewedErrors === 1 ? "error" : "errors"}`} />
        </MetricLedger>
        {evidenceId === null ? null : <EvidenceLink evidenceId={evidenceId} label="Open overview evidence" onSeek={onSeekEvidence} />}
      </section>
    </section>
  );
}
