import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { useLocation, useNavigationType } from "react-router-dom";

import type { components } from "../api/types.generated";
import { CourtlineRail } from "./CourtlineRail";

type Stage = components["schemas"]["Stage"];
type JobStatus = components["schemas"]["JobStatus"];

interface AppShellProps {
  children: ReactNode;
  matchId?: string;
  active?: "library" | "setup" | "processing" | "analysis";
  stage?: Stage | null;
  jobStatus?: JobStatus | null;
  progress?: number | null;
}

export function AppShell({ children, matchId, active, stage, jobStatus, progress }: AppShellProps) {
  const location = useLocation();
  const navigationType = useNavigationType();
  const mainRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (navigationType !== "POP" || location.key !== "default") {
      mainRef.current?.focus({ preventScroll: true });
    }
  }, [location.key, navigationType]);

  return (
    <div className="app-shell" data-workspace={active ?? "system"}>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <CourtlineRail matchId={matchId} active={active} stage={stage} jobStatus={jobStatus} progress={progress} />
      <main ref={mainRef} id="main-content" className="app-main" tabIndex={-1}>{children}</main>
    </div>
  );
}
