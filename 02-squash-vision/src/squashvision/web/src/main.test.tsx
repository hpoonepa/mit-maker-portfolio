// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./main";
import { jsonResponse } from "./test-utils";

const degradedHealth = {
  status: "degraded",
  version: "1.0.0",
  ffmpeg: { status: "unavailable" },
  worker: { status: "unavailable", architecture: "arm64", nativeAppleSilicon: true, mpsAvailable: true },
  models: { status: "missing", assets: [] },
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("application mount", () => {
  it("mounts the routed local ledger with truthful degraded components", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/v1/health") return Promise.resolve(jsonResponse(degradedHealth));
        if (url === "/api/v1/models") return Promise.resolve(jsonResponse([]));
        if (url.startsWith("/api/v1/matches")) return Promise.resolve(jsonResponse({ items: [], nextCursor: null }));
        throw new Error(`unexpected request: ${url}`);
      }),
    );

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Matches" })).toBeInTheDocument();
    expect(screen.getByText(/your video stays on this device/i)).toBeInTheDocument();
    fireEvent.click(screen.getByText("System status"));
    const unavailable = await within(screen.getByLabelText("Local system readiness")).findAllByText("unavailable");
    expect(unavailable).toHaveLength(2);
  });

  it("settles on retryable local API errors instead of a permanent loading state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    render(<App />);

    expect(await screen.findByText("Matches could not load")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry loading matches" })).toBeEnabled();
    expect(screen.queryByLabelText("Loading matches")).not.toBeInTheDocument();
  });
});
