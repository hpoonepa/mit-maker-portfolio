import { useMemo, useRef } from "react";
import type { CSSProperties, KeyboardEvent } from "react";

import type { components } from "../../api/types.generated";
import { formatMatchTime, isPlayableTimelineEvent } from "./analysis-model";

type TimelineItem = components["schemas"]["TimelineItem"];

interface EventTimelineProps {
  events: TimelineItem[];
  startUs: number;
  endUs: number;
  currentTimeUs: number;
  selectedEventId: string | null;
  onSeek: (timestampUs: number, eventId: string | null) => void;
}

const TRACK_BY_KIND: Record<string, string> = {
  rally: "rally",
  shot: "shot",
  error: "error",
  error_candidate: "error",
  review: "error",
  low_confidence: "confidence",
  reconstruction: "confidence",
};

function stringFromSummary(item: TimelineItem, ...names: string[]): string | null {
  for (const name of names) {
    const value = item.summary?.[name];
    if (typeof value === "string") return value;
  }
  return null;
}

function numberFromSummary(item: TimelineItem, name: string): number | null {
  const value = item.summary?.[name];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function eventLabel(item: TimelineItem): string {
  if (item.kind === "rally") return `Rally ${numberFromSummary(item, "ordinal") ?? "span"}`;
  if (item.kind === "shot") {
    const hitter = stringFromSummary(item, "hitter");
    const player = hitter === "near" ? "Player A" : hitter === "far" ? "Player B" : "Unknown player";
    return `Shot ${player} ${stringFromSummary(item, "shot_type", "shotKind") ?? "unclassified"}`;
  }
  if (item.kind.includes("error") || item.kind === "review") {
    return `Review error ${stringFromSummary(item, "issue", "outcome") ?? "candidate"}`;
  }
  if (item.kind === "contact") return "Court contact evidence";
  if (item.kind === "observationWindow" || item.kind === "observation_window") return "Evidence window";
  return "Match evidence";
}

export function EventTimeline({ events, startUs, endUs, currentTimeUs, selectedEventId, onSeek }: EventTimelineProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const durationUs = Math.max(1, Math.min(120_000_000, endUs - startUs));
  const visibleEndUs = startUs + durationUs;
  const visibleEvents = useMemo(
    () => events
      .filter(isPlayableTimelineEvent)
      .filter((item) => item.timestampUs < visibleEndUs && (item.endUs ?? item.timestampUs) >= startUs)
      .sort((left, right) => left.timestampUs - right.timestampUs)
      .slice(0, 400),
    [events, startUs, visibleEndUs],
  );
  const activeIndex = Math.max(0, visibleEvents.findIndex((item) => item.id === selectedEventId));
  const tickCount = Math.floor(durationUs / 5_000_000);
  const ticks = Array.from({ length: tickCount + 1 }, (_, index) => startUs + index * 5_000_000);
  const currentPercent = Math.max(0, Math.min(100, ((currentTimeUs - startUs) / durationUs) * 100));
  const selectedEvent = selectedEventId === null ? null : visibleEvents.find((item) => item.id === selectedEventId) ?? null;

  const focusEvent = (index: number): void => {
    const bounded = Math.max(0, Math.min(visibleEvents.length - 1, index));
    const item = visibleEvents[bounded];
    if (item === undefined) return;
    onSeek(item.timestampUs, item.id ?? null);
    viewportRef.current?.querySelectorAll<HTMLButtonElement>(".timeline-event")[bounded]?.focus();
  };

  const handleViewportKey = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (event.key !== "PageDown" && event.key !== "PageUp") return;
    event.preventDefault();
    const viewport = viewportRef.current;
    if (viewport === null) return;
    const delta = Math.max(1, viewport.clientWidth * 0.8) * (event.key === "PageDown" ? 1 : -1);
    viewport.scrollLeft = Math.max(0, viewport.scrollLeft + delta);
  };

  return (
    <section
      className="event-timeline"
      role="region"
      aria-label="Evidence timeline"
      data-window-seconds={Math.round(durationUs / 1_000_000)}
    >
      <header className="timeline-heading">
        <div><h2>Evidence timeline</h2></div>
        <p className="technical-id">{formatMatchTime(startUs)}–{formatMatchTime(visibleEndUs)} · {Math.max(1, Math.round(durationUs / 1_000_000))} s window</p>
      </header>
      <label className="timeline-mobile-picker">
        <span>Evidence events in this window</span>
        <select
          aria-label="Evidence events in this window"
          value={selectedEventId ?? ""}
          onChange={(event) => {
            const id = event.currentTarget.value;
            const item = visibleEvents.find((candidate) => (candidate.id ?? `${candidate.kind}-${candidate.timestampUs}`) === id);
            if (item !== undefined) onSeek(item.timestampUs, item.id ?? null);
          }}
        >
          <option value="">Choose an event</option>
          {visibleEvents.map((item) => {
            const id = item.id ?? `${item.kind}-${item.timestampUs}`;
            return <option key={id} value={id}>{formatMatchTime(item.timestampUs)} · {eventLabel(item)}</option>;
          })}
        </select>
        <small>{selectedEvent === null ? "No event selected" : `${formatMatchTime(selectedEvent.timestampUs)} · ${eventLabel(selectedEvent)}`}</small>
      </label>
      <div
        ref={viewportRef}
        className="timeline-viewport"
        data-testid="timeline-viewport"
        tabIndex={0}
        onKeyDown={handleViewportKey}
        aria-label="Scrollable event tracks; Page Up and Page Down pan"
      >
        <div className="timeline-canvas">
          <div className="timeline-ticks" aria-hidden="true">
            {ticks.map((timestamp) => (
              <span key={timestamp} style={{ "--timeline-left": `${((timestamp - startUs) / durationUs) * 100}%` } as CSSProperties}>
                {formatMatchTime(timestamp)}
              </span>
            ))}
          </div>
          {(["rally", "shot", "error", "confidence"] as const).map((track) => (
            <div key={track} className={`timeline-track timeline-track-${track}`} data-track={track}>
              <span className="timeline-track-label">{track}</span>
            </div>
          ))}
          <span className="timeline-playhead" style={{ "--timeline-left": `${currentPercent}%` } as CSSProperties} aria-hidden="true" />
          {visibleEvents.map((item, index) => {
            const id = item.id ?? `${item.kind}-${item.timestampUs}`;
            const left = ((item.timestampUs - startUs) / durationUs) * 100;
            const width = Math.max(0.4, (((item.endUs ?? item.timestampUs) - item.timestampUs) / durationUs) * 100);
            const track = TRACK_BY_KIND[item.kind] ?? (numberFromSummary(item, "confidence") !== null ? "confidence" : "shot");
            const confidence = numberFromSummary(item, "confidence");
            return (
              <button
                key={id}
                type="button"
                className={`timeline-event timeline-event-${track}`}
                style={{ "--timeline-left": `${left}%`, "--timeline-width": `${width}%` } as CSSProperties}
                aria-label={eventLabel(item)}
                aria-pressed={selectedEventId !== null && item.id === selectedEventId}
                tabIndex={index === activeIndex ? 0 : -1}
                data-confidence={confidence === null ? undefined : confidence < 0.5 ? "low" : "measured"}
                onClick={() => onSeek(item.timestampUs, item.id ?? null)}
                onKeyDown={(event) => {
                  if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
                  event.preventDefault();
                  focusEvent(index + (event.key === "ArrowRight" ? 1 : -1));
                }}
              >
                <span>{eventLabel(item)}</span>
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
