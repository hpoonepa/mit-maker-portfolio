import { Link, useRouteError } from "react-router-dom";
import type { RouteObject } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { AnalysisWorkspace } from "./features/analysis/AnalysisWorkspace";
import { MatchLibrary } from "./features/library/MatchLibrary";
import { ProcessingView } from "./features/processing/ProcessingView";
import { MatchSetup } from "./features/setup/MatchSetup";

function RouteFailure() {
  const error = useRouteError();
  return (
    <AppShell>
      <div className="action-state" role="alert">
        <p className="eyebrow">Route error</p>
        <h1>This view could not be opened</h1>
        <p>{error instanceof Error ? error.message : "The local route failed before it could render safely."}</p>
        <Link className="button-primary" to="/">Return to match ledger</Link>
      </div>
    </AppShell>
  );
}

function NotFound() {
  return (
    <AppShell>
      <div className="action-state not-found">
        <p className="eyebrow">404 · Outside the court</p>
        <h1>This court line ends here</h1>
        <p>The requested local view does not exist.</p>
        <Link className="button-primary" to="/">Return to match ledger</Link>
      </div>
    </AppShell>
  );
}

export const appRoutes: RouteObject[] = [
  { path: "/", element: <MatchLibrary />, errorElement: <RouteFailure /> },
  { path: "/matches/:matchId/setup", element: <MatchSetup />, errorElement: <RouteFailure /> },
  { path: "/matches/:matchId/processing", element: <ProcessingView />, errorElement: <RouteFailure /> },
  { path: "/matches/:matchId/analysis", element: <AnalysisWorkspace />, errorElement: <RouteFailure /> },
  { path: "*", element: <NotFound /> },
];
