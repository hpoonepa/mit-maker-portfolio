import { NavLink, useNavigate } from "react-router-dom";

import type { components } from "../api/types.generated";

type Stage = components["schemas"]["Stage"];
type JobStatus = components["schemas"]["JobStatus"];

interface CourtlineRailProps {
  matchId?: string;
  active?: "library" | "setup" | "processing" | "analysis";
  stage?: Stage | null;
  jobStatus?: JobStatus | null;
  progress?: number | null;
}

const STAGE_LABEL: Record<Stage, string> = {
  prepare: "Preparing media",
  calibration: "Court calibration",
  players: "Player tracking",
  ball: "Ball tracking",
  events: "Event detection",
  classification: "Shot classification",
  report: "Publishing report",
};

const WORKFLOW = [
  { id: "setup", number: "01", label: "Setup" },
  { id: "processing", number: "02", label: "Processing" },
  { id: "analysis", number: "03", label: "Analysis" },
] as const;

function workflowState(step: "setup" | "processing" | "analysis", active: CourtlineRailProps["active"]): "complete" | "current" | "available" {
  const currentIndex = WORKFLOW.findIndex((item) => item.id === active);
  const stepIndex = WORKFLOW.findIndex((item) => item.id === step);
  if (stepIndex === currentIndex) return "current";
  return stepIndex < currentIndex ? "complete" : "available";
}

export function CourtlineRail({ matchId, active = "library", stage = null, jobStatus = null, progress = null }: CourtlineRailProps) {
  const navigate = useNavigate();
  const progressPercent = jobStatus === "completed" ? 100 : progress === null ? null : Math.max(0, Math.min(100, Math.round(progress * 100)));
  return (
    <header className="courtline-rail">
      <NavLink className="rail-brand" to="/" aria-label="Matches">
        <span className="rail-mark" aria-hidden="true">
          <svg viewBox="0 0 28 32" width="28" height="32" fill="none" stroke="currentColor" strokeWidth="1.6">
            <path d="M3 3h22v26H3zM3 19h22M14 19v10M3 24h5v5M20 29v-5h5" />
            <path d="M3 8h22" opacity=".5" />
          </svg>
        </span>
        <strong>SquashVision</strong>
      </NavLink>
      {matchId === undefined ? (
        <a
          className="rail-add"
          href="#import"
          onClick={() => {
            const importDetails = document.getElementById("import");
            if (importDetails instanceof HTMLDetailsElement) importDetails.open = true;
          }}
        >
          Import video
        </a>
      ) : (
        <div className="rail-workflow">
          {(stage !== null || progressPercent !== null) && !(active === "analysis" && jobStatus === "completed") ? (
            <div className="rail-progress">
              <span>{jobStatus === "completed" ? "Analysis ready" : stage === null ? "Processing" : STAGE_LABEL[stage]}</span>
              <progress
                max={100}
                value={progressPercent ?? undefined}
                aria-label="Match processing progress"
                aria-valuenow={progressPercent ?? undefined}
              />
            </div>
          ) : null}
          <nav className="rail-nav" aria-label="Match workflow" data-active-step={active}>
            {WORKFLOW.map((item) => {
              const state = workflowState(item.id, active);
              return (
                <NavLink
                  key={item.id}
                  to={`/matches/${matchId}/${item.id}`}
                  data-state={state}
                  aria-current={state === "current" ? "step" : undefined}
                >
                  {item.label}
                  <span className="sr-only"> — {state} step</span>
                </NavLink>
              );
            })}
          </nav>
          <label className="rail-mobile-workflow">
            <span>Match workflow step</span>
            <select
              aria-label="Match workflow step"
              value={active === "library" ? "setup" : active}
              onChange={(event) => navigate(`/matches/${matchId}/${event.currentTarget.value}`)}
            >
              {WORKFLOW.map((item) => {
                const state = workflowState(item.id, active);
                return <option key={item.id} value={item.id}>{item.label} — {state}</option>;
              })}
            </select>
          </label>
        </div>
      )}
    </header>
  );
}
