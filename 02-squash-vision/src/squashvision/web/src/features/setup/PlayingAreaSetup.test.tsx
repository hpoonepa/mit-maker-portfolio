// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, renderApp } from "../../test-utils";
import { PlayingAreaSetup } from "./PlayingAreaSetup";
import { decodePlayingArea, validPlayingArea } from "./player-roi";

const empty = { revision: 0, sourceSha256: "a".repeat(64), frameSize: { width: 1280, height: 720 }, points: null, purpose: "player_detection_only" };
const polygon = [{ x: 374, y: 384 }, { x: 902, y: 384 }, { x: 1075, y: 719 }, { x: 202, y: 719 }];
beforeEach(() => { vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function editor(modelsReady = true) {
  const onStart = vi.fn();
  const onReady = vi.fn();
  renderApp(<PlayingAreaSetup matchId="match-1" modelsReady={modelsReady} starting={false} startError={null} onReadinessChange={onReady} onStart={onStart} />);
  return { onStart, onReady };
}

async function beginDrawing() {
  const video = await screen.findByLabelText("Playing area video");
  fireEvent.loadedMetadata(video);
  fireEvent.click(screen.getByRole("button", { name: "Draw playing area" }));
  const canvas = screen.getByRole("group", { name: "Draw playing area" });
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0, right: 640, bottom: 360, width: 640, height: 360, x: 0, y: 0, toJSON() {} });
  return canvas;
}

describe("playing area", () => {
  it("accepts convex source polygons and rejects crossed, duplicate, or incomplete points", () => {
    expect(validPlayingArea(polygon)).toBe(true);
    expect(validPlayingArea([...polygon].reverse())).toBe(true);
    expect(validPlayingArea([polygon[0], polygon[2], polygon[1], polygon[3]])).toBe(false);
    expect(validPlayingArea([polygon[0], polygon[0], polygon[1]])).toBe(false);
    expect(validPlayingArea(polygon.slice(0, 2))).toBe(false);
    expect(() => decodePlayingArea({ ...empty, sourceSha256: "unbound" })).toThrow();
    expect(() => decodePlayingArea({ ...empty, points: [{ x: -1, y: 0 }, ...polygon] })).toThrow();
  });

  it("saves source-scaled clicks and waits for server confirmation before tracking", async () => {
    let savedBody: unknown;
    let completeSave: ((response: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PUT") { savedBody = JSON.parse(String(init.body)); return new Promise<Response>((resolve) => { completeSave = resolve; }); }
      return Promise.resolve(jsonResponse(empty));
    }));
    const { onStart, onReady } = editor();
    const canvas = await beginDrawing();
    expect(screen.getByRole("button", { name: "Start tracking" })).toBeDisabled();
    for (const point of polygon) fireEvent.click(canvas, { clientX: point.x / 2, clientY: point.y / 2 });
    expect(screen.getByTestId("playing-area-polygon")).toHaveAttribute("points", "374,384 902,384 1075,719 202,719");
    fireEvent.click(screen.getByRole("button", { name: "Save playing area" }));
    await waitFor(() => expect(savedBody).toEqual({ expectedRevision: 0, sourceSha256: empty.sourceSha256, frameSize: empty.frameSize, points: polygon }));
    expect(screen.getByRole("button", { name: "Start tracking" })).toBeDisabled();
    completeSave?.(jsonResponse({ ...empty, revision: 1, points: polygon }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Start tracking" })).toBeEnabled());
    expect(onReady).toHaveBeenLastCalledWith(true);
    fireEvent.click(screen.getByRole("button", { name: "Start tracking" }));
    expect(onStart).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Reset area" }));
    expect(screen.getByRole("button", { name: "Start tracking" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save playing area" })).toBeDisabled();
  });
  it("supports keyboard points and retains the draft after a save conflict", async () => {
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => Promise.resolve(init?.method === "PUT"
      ? jsonResponse({ code: "source_changed", message: "source changed", requestId: "test", details: null }, 409)
      : jsonResponse(empty))));
    editor();
    const canvas = await beginDrawing();
    fireEvent.keyDown(canvas, { key: "Enter" });
    fireEvent.keyDown(canvas, { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(canvas, { key: "Enter" });
    fireEvent.keyDown(canvas, { key: "ArrowDown", shiftKey: true });
    fireEvent.keyDown(canvas, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Save playing area" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The source video or saved area changed");
    expect(screen.getByTestId("playing-area-polygon")).toHaveAttribute("points", "640,360 690,360 690,410");
    expect(screen.getByRole("button", { name: "Start tracking" })).toBeDisabled();
    fireEvent.keyDown(canvas, { key: "Backspace" });
    expect(screen.getByRole("button", { name: "Save playing area" })).toBeDisabled();
  });

  it("keeps the required-model gate even with a saved area", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse({ ...empty, revision: 1, points: polygon }))));
    editor(false);
    await screen.findByText("Playing area saved");
    expect(screen.getByRole("button", { name: "Start tracking" })).toBeDisabled();
    expect(screen.getByText(/Court distances require a separate calibration/)).toBeInTheDocument();
  });
});
