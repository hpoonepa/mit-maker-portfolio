import { EvidenceLink, UnavailableReport } from "./ReportPrimitives";
import { arrayValue, availability, metricValue, nestedRecord, numberValue, readableReason, recordValue, reportSection, stringArrayValue, stringValue } from "./report-model";
import type { ReportViewProps } from "./report-model";

interface TrajectoryPoint {
  id: string;
  x: number;
  y: number;
  provenance: "observed" | "reconstructed" | "ambiguous" | "canonical_court_contact";
  evidenceIds: string[];
  covariance: [[number, number], [number, number]] | null;
  sourceWidth: number | null;
  sourceHeight: number | null;
}

function covarianceMatrix(value: unknown): [[number, number], [number, number]] | null {
  if (!Array.isArray(value) || value.length !== 2) return null;
  const first = value[0];
  const second = value[1];
  if (!Array.isArray(first) || first.length !== 2 || !Array.isArray(second) || second.length !== 2) return null;
  const [xx, xy] = first;
  const [yx, yy] = second;
  if (typeof xx !== "number" || !Number.isFinite(xx) || typeof xy !== "number" || !Number.isFinite(xy) || typeof yx !== "number" || !Number.isFinite(yx) || typeof yy !== "number" || !Number.isFinite(yy)) return null;
  return [[xx, xy], [yx, yy]];
}

function trajectoryPoints(payload: Record<string, unknown>, xName: string, yName: string, allowCanonical = false, requireCovariance = false): TrajectoryPoint[] {
  const points: TrajectoryPoint[] = [];
  for (const candidate of arrayValue(payload, "items").slice(0, 1_000)) {
    const value = recordValue(candidate);
    if (value === null) continue;
    const id = stringValue(value, "shot_id") ?? stringValue(value, "evidence_id");
    const x = numberValue(value, xName);
    const y = numberValue(value, yName);
    const provenanceValue = stringValue(value, "provenance");
    const covariance = covarianceMatrix(value.covariance);
    if (id === null || x === null || y === null || (requireCovariance && covariance === null) || (provenanceValue !== "observed" && provenanceValue !== "reconstructed" && provenanceValue !== "ambiguous" && (!allowCanonical || provenanceValue !== "canonical_court_contact"))) continue;
    points.push({ id, x, y, provenance: provenanceValue, evidenceIds: stringArrayValue(value, "evidence_ids"), covariance, sourceWidth: numberValue(value, "source_width"), sourceHeight: numberValue(value, "source_height") });
  }
  return points;
}

function consistentSourceDimensions(points: TrajectoryPoint[]): { width: number; height: number } | "missing" | "inconsistent" {
  const first = points[0];
  if (
    first === undefined
    || first.sourceWidth === null
    || first.sourceHeight === null
    || first.sourceWidth <= 0
    || first.sourceHeight <= 0
  ) {
    return "missing";
  }
  for (const point of points) {
    if (
      point.sourceWidth === null
      || point.sourceHeight === null
      || point.sourceWidth <= 0
      || point.sourceHeight <= 0
    ) {
      return "missing";
    }
    if (point.sourceWidth !== first.sourceWidth || point.sourceHeight !== first.sourceHeight) {
      return "inconsistent";
    }
  }
  return { width: first.sourceWidth, height: first.sourceHeight };
}

export function TrajectoryReport({ report, onSeekEvidence }: ReportViewProps) {
  const section = reportSection(report, "trajectory");
  if (section === null) return <UnavailableReport title="Trajectory" reason="not_published" />;
  const state = availability(section.payload);
  if (!state.available) return <UnavailableReport title="Trajectory" reason={state.reason} />;
  const speed = metricValue(section.payload, "average_speed_m_s");
  const measuredShots = numberValue(section.payload, "measured_shot_count");
  const imageTrajectory = nestedRecord(section.payload, "image_trajectory");
  const imageAvailability = imageTrajectory === null ? { available: false, reason: "not_published" } : availability(imageTrajectory);
  const imageCandidates = imageTrajectory === null || !imageAvailability.available ? [] : trajectoryPoints(imageTrajectory, "x_px", "y_px", false, true);
  const sourceDimensions = imageCandidates.length === 0 ? "missing" : consistentSourceDimensions(imageCandidates);
  const imagePoints = typeof sourceDimensions === "object" ? imageCandidates : [];
  const imageUnavailableReason = !imageAvailability.available
    ? imageAvailability.reason
    : imageCandidates.length === 0
      ? "image_space_provenance_not_published"
      : sourceDimensions === "inconsistent"
        ? "source_dimensions_inconsistent"
        : "source_dimensions_missing_or_invalid";
  const courtTrajectory = nestedRecord(section.payload, "court_trajectory");
  const courtAvailability = courtTrajectory === null ? { available: false, reason: "not_published" } : availability(courtTrajectory);
  const calibrationRevision = courtTrajectory === null ? null : numberValue(courtTrajectory, "calibration_revision");
  const courtCandidates = courtTrajectory === null || !courtAvailability.available ? [] : trajectoryPoints(courtTrajectory, "x_m", "y_m", true);
  const courtPoints = calibrationRevision === null ? [] : courtCandidates;
  const courtUnavailableReason = calibrationRevision === null
    ? "missing_calibration"
    : !courtAvailability.available
      ? courtAvailability.reason
      : courtPoints.length === 0 ? "insufficient_sample" : null;
  const exclusions = nestedRecord(section.payload, "control_point_exclusions") ?? {};
  const exclusionEntries = Object.entries(exclusions).filter((entry): entry is [string, number] => typeof entry[1] === "number" && Number.isFinite(entry[1]));
  const excludedTotal = exclusionEntries.reduce((total, [, count]) => total + count, 0);

  return (
    <section className="report-view" aria-labelledby="trajectory-title">
      <header className="report-heading"><h2 id="trajectory-title">Trajectory</h2></header>
      <div className="trajectory-layout">
        {imagePoints.length === 0 ? <div className="report-inline-unavailable"><strong>Image trajectory unavailable</strong><p>{readableReason(imageUnavailableReason)}. Finish ball tracking to view the path in the video.</p></div> : <svg className="trajectory-plot" viewBox={`0 0 ${typeof sourceDimensions === "object" ? sourceDimensions.width : 0} ${typeof sourceDimensions === "object" ? sourceDimensions.height : 0}`} role="img" aria-label="Image-space ball trajectory"><title>Ball positions in the video, showing observed, estimated, and uncertain positions</title>{imagePoints.map((point) => <ellipse key={point.id} className={`trajectory-point ${point.provenance}`} cx={point.x} cy={point.y} rx={Math.max(4, Math.sqrt(point.covariance?.[0][0] ?? 0) * 2)} ry={Math.max(4, Math.sqrt(point.covariance?.[1][1] ?? 0) * 2)}><title>{point.id}: {point.provenance} covariance uncertainty</title></ellipse>)}</svg>}
        <div>
          {courtPoints.length === 0 ? <div className="report-inline-unavailable"><strong>Court trajectory unavailable</strong><p>{readableReason(courtUnavailableReason)}. Calibrate the court and finish tracking to view contact positions.</p></div> : <svg className="trajectory-plot" viewBox="0 0 640 975" role="img" aria-label="Calibration-gated court contact trajectory"><title>Court contact trajectory at calibration revision {calibrationRevision}</title><rect className="trajectory-court" x="1" y="1" width="638" height="973" />{courtPoints.map((point) => <circle key={point.id} className={`trajectory-point ${point.provenance}`} cx={point.x * 100} cy={975 - point.y * 100} r="10"><title>{point.id}: {point.provenance === "canonical_court_contact" ? "court contact" : point.provenance}</title></circle>)}</svg>}
          <dl className="trajectory-ledger">
            <div><dt>Metric ball speed</dt><dd>{speed.available && speed.value !== null ? `${speed.value.toFixed(1)} m/s` : <>Metric ball speed unavailable · {readableReason(speed.reason)}</>}</dd></div>
            <div><dt>Measured shots</dt><dd>{measuredShots === null ? "Unavailable · sample not published" : `${measuredShots} measured shots`}</dd></div>
            <div><dt>Valid control points</dt><dd>{imagePoints.length + courtPoints.length} measured · {excludedTotal} excluded</dd></div>
            <div><dt>Video positions</dt><dd>{imagePoints.length === 0 ? `Unavailable · ${readableReason(imageUnavailableReason)}` : `${imagePoints.length} tracked positions`}</dd></div>
            <div><dt>Court calibration</dt><dd>{courtPoints.length === 0 ? `Unavailable · ${readableReason(courtUnavailableReason)}` : `Revision ${calibrationRevision} · ${courtPoints.length} contacts`}</dd></div>
            <div><dt>Exclusion reasons</dt><dd>{exclusionEntries.map(([name, value]) => `${value} ${readableReason(name)}`).join(" · ") || "No exclusions published"}</dd></div>
          </dl>
        </div>
      </div>
      <div className="evidence-row">{[...imagePoints, ...courtPoints].map((point) => <EvidenceLink key={`${point.provenance}-${point.id}`} evidenceId={point.evidenceIds[0] ?? point.id} label={`Seek trajectory ${point.id}`} onSeek={onSeekEvidence} />)}</div>
    </section>
  );
}
