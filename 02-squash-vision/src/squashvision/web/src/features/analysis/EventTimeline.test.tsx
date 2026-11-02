// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EventTimeline } from "./EventTimeline";

const events = [
  { id: "rally-1", kind: "rally", timestampUs: 10_000_000, endUs: 18_000_000, evidenceIds: ["ev-rally"], summary: { ordinal: 1 } },
  { id: "shot-1", kind: "shot", timestampUs: 12_250_000, evidenceIds: ["ev-shot"], summary: { hitter: "near", shot_type: "drive" } },
  { id: "error-1", kind: "error_candidate", timestampUs: 15_000_000, evidenceIds: ["ev-error"], summary: { review_required: true, confidence: 0.32 } },
];

afterEach(cleanup);

describe("bounded evidence timeline", () => {
  it("renders real ticks and evidence tracks, seeks one shared path, and roves focus", () => {
    const seek = vi.fn();
    renderTimeline(seek);
    expect(screen.getByRole("region", { name: "Evidence timeline" })).toHaveAttribute("data-window-seconds", "30");
    expect(screen.getByText("0:00–0:30 · 30 s window")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Shot.*drive/i })).toHaveAttribute("tabindex", "0");
    fireEvent.click(screen.getByRole("button", { name: /Review error/i }));
    expect(seek).toHaveBeenCalledWith(15_000_000, "error-1");

    const shot = screen.getByRole("button", { name: /Shot.*drive/i });
    shot.focus();
    fireEvent.keyDown(shot, { key: "ArrowRight" });
    expect(screen.getByRole("button", { name: /Review error/i })).toHaveFocus();
  });
  it("offers a labelled compact event picker without replacing the desktop tabular timeline", () => {
    const seek = vi.fn();
    renderTimeline(seek);
    const picker = screen.getByRole("combobox", { name: "Evidence events in this window" });

    expect(picker).toHaveValue("shot-1");
    expect(screen.getByRole("option", { name: /Review error/i })).toBeInTheDocument();
    fireEvent.change(picker, { target: { value: "error-1" } });

    expect(seek).toHaveBeenCalledWith(15_000_000, "error-1");
    expect(screen.getByTestId("timeline-viewport")).toBeInTheDocument();
  });

  it("offers keyboard-equivalent panning without body overflow", () => {
    renderTimeline(vi.fn());
    const viewport = screen.getByTestId("timeline-viewport");
    Object.defineProperty(viewport, "clientWidth", { value: 400 });
    fireEvent.keyDown(viewport, { key: "PageDown" });
    expect(viewport.scrollLeft).toBeGreaterThan(0);
  });

  it("keeps observation-window metadata out of tracks and leaves an empty selection neutral", () => {
    const seek = vi.fn();
    render(<EventTimeline events={[
      { id: null, kind: "observationWindow", timestampUs: 0, endUs: 30_000_000, evidenceIds: [] },
      { id: "window-2", kind: "observation_window", timestampUs: 0, endUs: 30_000_000, evidenceIds: [] },
      ...events,
    ]} startUs={0} endUs={30_000_000} currentTimeUs={0} selectedEventId={null} onSeek={seek} />);

    expect(screen.queryByRole("button", { name: "Evidence window" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Evidence window/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { pressed: true })).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Evidence events in this window" })).toHaveValue("");
    expect(screen.getByText("No event selected")).toBeInTheDocument();
    expect(seek).not.toHaveBeenCalled();
  });
});

function renderTimeline(onSeek: (timestampUs: number, eventId: string | null) => void) {
  return render(
    <EventTimeline
      events={events}
      startUs={0}
      endUs={30_000_000}
      currentTimeUs={12_250_000}
      selectedEventId="shot-1"
      onSeek={onSeek}
    />,
  );
}
