import { useState } from "react";
import type { KeyboardEvent } from "react";
import { formatMatchTime, shouldIgnorePlaybackShortcut } from "../analysis/analysis-model";

import type { CorrectionImpact, ReviewItem } from "./review-model";

export type ReviewShortcut = "accept" | "reject" | "cycle_hitter" | "cycle_shot" | "cycle_outcome";

interface ReviewQueueProps {
  items: ReviewItem[];
  currentIndex: number;
  reviewedCount: number;
  totalCount: number;
  onNavigate: (index: number) => void;
  onSeek: (timestampUs: number, eventId: string) => void;
  onShortcut: (shortcut: ReviewShortcut) => void;
  activeImpact?: CorrectionImpact | null;
}

const SHORTCUT_BY_KEY: Record<string, ReviewShortcut> = {
  a: "accept",
  r: "reject",
  h: "cycle_hitter",
  s: "cycle_shot",
  o: "cycle_outcome",
};

function titleCase(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/gu, (letter) => letter.toUpperCase());
}

export function ReviewQueue({ items, currentIndex, reviewedCount, totalCount, onNavigate, onSeek, onShortcut, activeImpact = null }: ReviewQueueProps) {
  const item = items[currentIndex] ?? null;
  const [announcement, setAnnouncement] = useState("");
  const handleKeyDown = (event: KeyboardEvent<HTMLElement>): void => {
    if (shouldIgnorePlaybackShortcut(event.target)) return;
    if (event.key === "[" || event.key === "]") {
      event.preventDefault();
      onNavigate(currentIndex + (event.key === "]" ? 1 : -1));
      setAnnouncement(event.key === "]" ? "Next review item" : "Previous review item");
      return;
    }
    const shortcut = SHORTCUT_BY_KEY[event.key.toLowerCase()];
    if (shortcut === undefined) return;
    event.preventDefault();
    onShortcut(shortcut);
    setAnnouncement(`${shortcut.replaceAll("_", " ")} selected`);
  };

  return (
    <section className="review-queue" role="region" aria-label="Correction review queue" tabIndex={0} onKeyDown={handleKeyDown}>
      <header className="review-heading">
        <div><h2>{reviewedCount} of {totalCount} reviewed</h2></div>
        <span className="mono">{item === null ? "Queue clear" : `${currentIndex + 1} / ${items.length}`}</span>
      </header>
      {item === null ? (
        <div className="empty-state"><h3>Review complete</h3><p>All items in this report have been reviewed.</p></div>
      ) : (
        <>
          <div className="review-evidence-readout">
            <button type="button" className="review-time" onClick={() => onSeek(item.timestampUs, item.id)}>
              {formatMatchTime(item.timestampUs, true)}{item.endUs === null ? "" : `–${formatMatchTime(item.endUs, true)}`}
            </button>
            <strong>{item.provenance === "unavailable" ? "Evidence source unavailable" : `${titleCase(item.provenance)} evidence`}</strong>
            <span className="mono">{item.confidence === null ? "Confidence unavailable" : `Confidence ${Math.round(item.confidence * 100)}%`}</span>
          </div>
          <details className="review-technical">
            <summary>Prediction details</summary>
            <dl className="review-detail-ledger">
              <div><dt>Issue</dt><dd>{titleCase(item.issue)}</dd></div>
              <div><dt>Prediction</dt><dd>{Object.entries(item.probabilities).length === 0 ? "Prediction probabilities unavailable" : Object.entries(item.probabilities).map(([name, probability]) => `${name} ${Math.round(probability * 100)}%`).join(" · ")}</dd></div>
              <div><dt>Reasons</dt><dd>{item.reasons.length === 0 ? "No reason provided" : item.reasons.join(" · ")}</dd></div>
              <div><dt>Reports updated after saving</dt><dd>{(activeImpact?.invalidatedSections ?? item.invalidatedSections).length === 0 ? "Affected reports unavailable" : (activeImpact?.invalidatedSections ?? item.invalidatedSections).map(titleCase).join(", ")}</dd></div>
              <div><dt>Statistics updated after saving</dt><dd>{(activeImpact?.invalidatedStats ?? item.invalidatedStats).length === 0 ? "Affected statistics unavailable" : (activeImpact?.invalidatedStats ?? item.invalidatedStats).map(titleCase).join(", ")}</dd></div>
              <div><dt>Evidence range</dt><dd>{formatMatchTime(item.evidenceStartTimestampUs, true)}–{formatMatchTime(item.evidenceEndTimestampUs, true)} · frames {item.evidenceStartFrameIndex ?? "unavailable"}–{item.evidenceEndFrameIndex ?? "unavailable"}</dd></div>
              <div><dt>Evidence IDs</dt><dd>{item.evidenceIds.length === 0 ? "No evidence IDs" : item.evidenceIds.join(", ")}</dd></div>
            </dl>
          </details>
          <nav className="review-navigation" aria-label="Review navigation">
            <button type="button" disabled={currentIndex <= 0} onClick={() => onNavigate(currentIndex - 1)}>Previous item [</button>
            <button type="button" disabled={currentIndex >= items.length - 1} onClick={() => onNavigate(currentIndex + 1)}>Next item ]</button>
          </nav>
        </>
      )}
      <p className="review-shortcuts mono">A accept · R reject · H hitter · S shot · O outcome · [ ] navigate</p>
      <output className="sr-only" aria-live="polite">{announcement || (item === null ? "Review queue complete" : `Selected review item ${currentIndex + 1} of ${items.length}`)}</output>
    </section>
  );
}
