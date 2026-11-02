export interface ObservationWindow {
  startUs: number;
  endUs: number;
}

export function isPlayableTimelineEvent(item: { kind: string }): boolean {
  return item.kind !== "observationWindow" && item.kind !== "observation_window";
}

const BEFORE_US = 10_000_000;
const AFTER_US = 20_000_000;
export const OBSERVATION_WINDOW_STEP_US = 10_000_000;

export function boundedObservationWindow(currentTimeUs: number, durationUs: number): ObservationWindow {
  const boundedDuration = Math.max(0, durationUs);
  const boundedCurrent = Math.min(boundedDuration, Math.max(0, currentTimeUs));
  // Keep the query key stable as video frames advance, with evidence buffered
  // on either side of the active ten-second segment.
  const anchorUs = Math.floor(boundedCurrent / OBSERVATION_WINDOW_STEP_US) * OBSERVATION_WINDOW_STEP_US;
  return {
    startUs: Math.max(0, anchorUs - BEFORE_US),
    endUs: Math.min(boundedDuration, anchorUs + AFTER_US),
  };
}

export interface EvidenceStep {
  timestampUs: number;
  exact: boolean;
}

export function evidenceStep(timestamps: readonly number[], currentTimeUs: number, direction: -1 | 1): EvidenceStep | null {
  if (timestamps.length === 0) return null;
  const ordered = [...new Set(timestamps)].sort((left, right) => left - right);
  const exact = ordered.includes(currentTimeUs);
  if (direction > 0) {
    const next = ordered.find((timestamp) => timestamp > currentTimeUs);
    return { timestampUs: next ?? ordered[ordered.length - 1], exact };
  }
  for (let index = ordered.length - 1; index >= 0; index -= 1) {
    if (ordered[index] < currentTimeUs) return { timestampUs: ordered[index], exact };
  }
  return { timestampUs: ordered[0], exact };
}

export function shouldIgnorePlaybackShortcut(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.matches("input, select, textarea, button, a[href], [role='button'], [role='tab'], [contenteditable='true']");
}

export function formatMatchTime(timestampUs: number, includeMillis = false): string {
  const totalMilliseconds = Math.max(0, Math.round(timestampUs / 1_000));
  const totalSeconds = Math.floor(totalMilliseconds / 1_000);
  const hours = Math.floor(totalSeconds / 3_600);
  const minutes = Math.floor((totalSeconds % 3_600) / 60);
  const seconds = totalSeconds % 60;
  const base = hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${minutes}:${String(seconds).padStart(2, "0")}`;
  return includeMillis ? `${base}.${String(totalMilliseconds % 1_000).padStart(3, "0")}` : base;
}
