// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, Link, Route, RouterProvider, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { appRoutes } from "./router";
import { AppShell } from "./components/AppShell";
import { renderApp } from "./test-utils";

afterEach(cleanup);

describe("application routes", () => {
  it("makes unknown local routes finite and recoverable", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const router = createMemoryRouter(appRoutes, { initialEntries: ["/not-a-real-place"] });
    render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("heading", { name: "This court line ends here" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Return to match ledger" })).toHaveAttribute("href", "/");
  });
  it("focuses main content after client navigation without stealing initial focus", async () => {
    renderApp(
      <Routes>
        <Route path="/" element={<AppShell><h1>First page</h1><Link to="/second">Next page</Link></AppShell>} />
        <Route path="/second" element={<AppShell><h1>Second page</h1></AppShell>} />
      </Routes>,
    );
    const initialMain = screen.getByRole("main");
    expect(initialMain).not.toHaveFocus();
    fireEvent.click(screen.getByRole("link", { name: "Next page" }));
    await screen.findByRole("heading", { name: "Second page" });
    await waitFor(() => expect(screen.getByRole("main")).toHaveFocus());
  });
  it("registers analysis as a real route and gives workflow links explicit states", () => {
    expect(appRoutes.some((route) => route.path === "/matches/:matchId/analysis")).toBe(true);
    renderApp(<Routes><Route path="/matches/:matchId/analysis" element={<AppShell matchId="match-1" active="analysis"><h1>Analysis</h1></AppShell>} /></Routes>, "/matches/match-1/analysis");
    expect(screen.getByRole("link", { name: /Analysis.*current/i })).toHaveAttribute("href", "/matches/match-1/analysis");
    expect(screen.getByRole("link", { name: /Analysis.*current/i })).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("link", { name: /Setup.*complete/i })).toHaveAttribute("data-state", "complete");
    expect(screen.getByRole("link", { name: /Processing.*complete/i })).toHaveAttribute("data-state", "complete");
    expect(screen.getByRole("combobox", { name: "Match workflow step" })).toHaveValue("analysis");
  });
  it("publishes the current processing stage and progress in the contextual workflow rail", () => {
    renderApp(
      <AppShell matchId="match-1" active="processing" stage="ball" progress={0.5}>
        <h1>Processing</h1>
      </AppShell>,
    );
    expect(screen.getByRole("navigation", { name: "Match workflow" })).toHaveAttribute("data-active-step", "processing");
    expect(screen.getByRole("progressbar", { name: "Match processing progress" })).toHaveAttribute("aria-valuenow", "50");
    expect(screen.getByText("Ball tracking")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Setup.*complete/i })).toHaveAttribute("data-state", "complete");
    expect(screen.getByRole("link", { name: /Processing.*current/i })).toHaveAttribute("data-state", "current");
    expect(screen.getByRole("link", { name: /Analysis.*available/i })).toHaveAttribute("data-state", "available");
  });
  it("keeps workflow navigation contextual to a selected match", () => {
    renderApp(<AppShell active="library"><h1>Library</h1></AppShell>);
    expect(screen.queryByRole("navigation", { name: "Match workflow" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Match workflow step" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Matches" })).toHaveAttribute("href", "/");
  });

  it.each([
    ["completed", "Analysis ready"],
    ["running", "Publishing report"],
  ] as const)("uses explicit %s job status when report progress is 100 percent", (jobStatus, label) => {
    renderApp(<AppShell matchId="match-1" active="analysis" stage="report" jobStatus={jobStatus} progress={1}><h1>Analysis</h1></AppShell>, "/matches/match-1/analysis");
    if (jobStatus === "completed") {
      expect(screen.getByRole("link", { name: "Analysis — current step" })).toHaveAttribute("aria-current", "step");
      expect(screen.queryByRole("progressbar", { name: "Match processing progress" })).not.toBeInTheDocument();
    } else {
      expect(screen.getByText(label)).toBeInTheDocument();
      expect(screen.getByRole("progressbar", { name: "Match processing progress" })).toHaveAttribute("aria-valuenow", "100");
    }
    expect(screen.queryByText(jobStatus === "completed" ? "Publishing report" : "Analysis ready")).not.toBeInTheDocument();
  });


});
