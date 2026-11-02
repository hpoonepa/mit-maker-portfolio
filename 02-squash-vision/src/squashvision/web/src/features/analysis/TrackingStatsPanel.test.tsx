// @vitest-environment jsdom
// Checks tracking totals, coverage, player filters and unknown coordinates.

import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, renderApp } from "../../test-utils";
import { MatchSummary, TrackingStatsPanel, TrackingStatsView } from "./TrackingStatsPanel";
import { decodeTrackingStats } from "./tracking-stats";
import { trackingStatsFixture } from "./tracking-stats.test-utils";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function expandContacts() {
  const details = screen.getByText("Contact positions").closest("details")!;
  details.open = true;
  fireEvent(details, new Event("toggle"));
  return screen.findByRole("table", { name: "Contact locations and confidence" });
}

describe("tracking statistics", () => {
  it("loads the summary only after first open and retains it when collapsed", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(trackingStatsFixture()));
    vi.stubGlobal("fetch", fetchMock);
    renderApp(<MatchSummary matchId="match" reportRevision={2} onSeekVideo={vi.fn()} />);
    expect(fetchMock).not.toHaveBeenCalled();
    const details = screen.getByText("Match summary").closest("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    await screen.findByText("12.4");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    details.open = false;
    fireEvent(details, new Event("toggle"));
    details.open = true;
    fireEvent(details, new Event("toggle"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps measurements compact and labels partial coverage and estimates", () => {
    renderApp(<TrackingStatsView stats={trackingStatsFixture()} matchId="match" onSeekVideo={vi.fn()} />);
    expect(screen.getByText("12.4")).toBeInTheDocument();
    expect(screen.getByText("8.2")).toBeInTheDocument();
    expect(screen.getByText("14.0")).toBeInTheDocument();
    expect(screen.getByText("10.0 s tracked · 50% coverage")).toBeInTheDocument();
    expect(screen.getByText(/A\/B identities unverified/)).toHaveTextContent("Ball speed assumes motion on the floor plane.");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("maps front-left coordinates correctly and seeks the exact proxy frame from either view", async () => {
    const seek = vi.fn();
    renderApp(<TrackingStatsView stats={trackingStatsFixture()} matchId="match" onSeekVideo={seek} />);
    const table = await expandContacts();
    const court = screen.getByRole("group", { name: "Player positions at contact on the court" });
    const marker = within(court).getByRole("button", { name: /Contact 1, Player A/ });
    expect(marker.querySelector("circle")).toHaveAttribute("cx", "100");
    expect(marker.querySelector("circle")).toHaveAttribute("cy", "200");
    fireEvent.keyDown(marker, { key: "Enter" });
    expect(seek).toHaveBeenLastCalledWith(12_500_000);
    fireEvent.click(within(table).getByRole("button", { name: /Play contact 2/ }));
    expect(seek).toHaveBeenLastCalledWith(14_033_333);
    expect(within(table).getByText("1.00 / 2.00")).toBeInTheDocument();
    expect(within(table).getByText("80% confidence")).toBeInTheDocument();
    expect(within(table).getAllByText("Needs review")).toHaveLength(2);
  });

  it("retains unknown hitters and unavailable positions without invented coordinates or video times", async () => {
    const seek = vi.fn();
    renderApp(<TrackingStatsView stats={trackingStatsFixture()} matchId="match" onSeekVideo={seek} />);
    const table = await expandContacts();
    fireEvent.click(screen.getByRole("button", { name: "Unknown" }));
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    expect(within(table).getByText("Unknown hitter")).toBeInTheDocument();
    expect(within(table).getByText("Unavailable")).toBeInTheDocument();
    const unavailable = within(table).getByRole("button", { name: /Play contact 3/ });
    expect(unavailable).toBeDisabled();
    fireEvent.click(unavailable);
    expect(seek).not.toHaveBeenCalled();
    expect(screen.getByText("No mapped contacts in this selection.")).toBeInTheDocument();
  });

  it("shows unavailable metric values until calibration exists, while preserving a measured zero", () => {
    const original = trackingStatsFixture();
    const stats = trackingStatsFixture({
      calibrationAvailable: false, calibrationRevision: null, calibrationReason: "missing_calibration",
      players: original.players.map((player) => ({ ...player, distanceM: null })),
      contacts: [], ballSpeed: { ...original.ballSpeed, medianMps: null, p90Mps: null },
    });
    const view = renderApp(<TrackingStatsView stats={stats} matchId="match" onSeekVideo={vi.fn()} />);
    expect(screen.getAllByText("Unavailable")).toHaveLength(3);
    expect(screen.getByRole("link", { name: "Open court setup" })).toHaveAttribute("href", "/matches/match/setup");
    expect(screen.queryByText("0.0")).not.toBeInTheDocument();
    view.unmount();
    renderApp(<TrackingStatsView stats={trackingStatsFixture({ players: original.players.map((player) => ({ ...player, distanceM: 0 })) })} matchId="match" onSeekVideo={vi.fn()} />);
    expect(screen.getAllByText("0.0")).toHaveLength(2);
  });

  it("keeps an unassigned contact playable when its video frame is known", async () => {
    const base = trackingStatsFixture();
    const seek = vi.fn();
    renderApp(<TrackingStatsView stats={{ ...base, contacts: [{ ...base.contacts[2], proxyTimestampUs: 15_966_667 }] }} matchId="match" onSeekVideo={seek} />);
    const table = await expandContacts();
    fireEvent.click(within(table).getByRole("button", { name: /Play contact 1, unknown hitter/ }));
    expect(seek).toHaveBeenCalledWith(15_966_667);
    expect(within(table).getByText("Unavailable")).toBeInTheDocument();
  });

  it("paginates contact rows and resets the page when filtering", async () => {
    const base = trackingStatsFixture();
    const contacts = Array.from({ length: 27 }, (_, index) => ({ ...base.contacts[index % 2], id: `contact-${index}`, timestampUs: index * 1_000_000 }));
    renderApp(<TrackingStatsView stats={{ ...base, contacts }} matchId="match" onSeekVideo={vi.fn()} />);
    const table = await expandContacts();
    expect(within(table).getAllByRole("row")).toHaveLength(26);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Player B" }));
    expect(within(table).getAllByRole("row")).toHaveLength(14);
    expect(screen.queryByRole("navigation", { name: "Contact pages" })).not.toBeInTheDocument();
  });

  it("rejects malformed metric, identity, coordinate and calibration data", () => {
    const valid = trackingStatsFixture();
    expect(decodeTrackingStats(valid)).toEqual(valid);
    expect(() => decodeTrackingStats({ ...valid, players: [valid.players[0], valid.players[0]] })).toThrow();
    expect(() => decodeTrackingStats({ ...valid, ballSpeed: { ...valid.ballSpeed, medianMps: Number.NaN } })).toThrow();
    expect(() => decodeTrackingStats({ ...valid, contacts: [{ ...valid.contacts[0], position: [10, 2] }] })).toThrow();
    expect(() => decodeTrackingStats({ ...valid, calibrationAvailable: false })).toThrow();
    expect(() => decodeTrackingStats({ ...valid, contacts: [{ ...valid.contacts[0], proxyTimestampUs: undefined }] })).toThrow();
  });

  it("clears previous metrics on revision changes and refuses a mismatched response", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(trackingStatsFixture()));
    let resolveNext!: (response: Response) => void;
    fetchMock.mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveNext = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const ui = (revision: number) => <QueryClientProvider client={client}><MemoryRouter><TrackingStatsPanel matchId="match" reportRevision={revision} onSeekVideo={vi.fn()} /></MemoryRouter></QueryClientProvider>;
    const view = render(ui(2));
    await screen.findByText("12.4");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/matches/match/reports/2/tracking-stats");
    view.rerender(ui(3));
    expect(screen.getByText("Loading measurements…")).toBeInTheDocument();
    expect(screen.queryByText("12.4")).not.toBeInTheDocument();
    await waitFor(() => expect(resolveNext).toBeDefined());
    resolveNext(jsonResponse(trackingStatsFixture({ reportRevision: 2 })));
    await screen.findByText("Measurements unavailable.");
    expect(screen.queryByText("12.4")).not.toBeInTheDocument();
  });

  it("allows retry after a failed request", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(jsonResponse(trackingStatsFixture())));
    renderApp(<TrackingStatsPanel matchId="match" reportRevision={2} onSeekVideo={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry measurements" }));
    await screen.findByText("12.4");
  });
});
