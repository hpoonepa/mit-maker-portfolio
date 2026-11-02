import type { ReactNode } from "react";

import { readableReason, unavailableAction } from "./report-model";

export function UnavailableReport({ title, reason }: { title: string; reason: string | null }) {
  return (
    <div className="report-unavailable" role="status">
      <h2>{title} unavailable</h2>
      <p>{readableReason(reason)}.</p>
      <p>{unavailableAction(reason)}</p>
    </div>
  );
}

export function EvidenceLink({ evidenceId, label = "Seek evidence", onSeek }: { evidenceId: string | null; label?: string; onSeek: (evidenceId: string) => void }) {
  return <button type="button" className="evidence-link" disabled={evidenceId === null} onClick={() => { if (evidenceId !== null) onSeek(evidenceId); }}>{evidenceId === null ? "Evidence unavailable" : label}</button>;
}

export function MetricLedger({ children }: { children: ReactNode }) {
  return <dl className="metric-ledger">{children}</dl>;
}

export function MetricRow({ label, value, availability, sample }: { label: string; value: ReactNode; availability: string; sample: string }) {
  return (
    <div className="metric-row">
      <dt>{label}</dt>
      <dd className="metric-value">{value}</dd>
      <dd className="metric-provenance"><span>{availability}</span><span>{sample}</span></dd>
    </div>
  );
}
