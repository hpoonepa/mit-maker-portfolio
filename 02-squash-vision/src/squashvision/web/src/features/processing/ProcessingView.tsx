import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { request, streamJobEvents } from "../../api/client";
import { decodeJob, decodeJobEvent, decodeMatchDetail } from "../../api/decoders";
import type { JobDetail } from "../../api/decoders";
import type { components } from "../../api/types.generated";
import { AppShell } from "../../components/AppShell";

type Stage = components["schemas"]["Stage"];
type JobStatus = components["schemas"]["JobStatus"];

const STAGES: Array<{ value: Stage; label: string; activeLabel: string }> = [
  { value: "prepare", label: "Prepare", activeLabel: "Preparing media" },
  { value: "calibration", label: "Calibration", activeLabel: "Checking calibration" },
  { value: "players", label: "Players", activeLabel: "Tracking players" },
  { value: "ball", label: "Ball", activeLabel: "Ball tracking" },
  { value: "events", label: "Events", activeLabel: "Detecting events" },
  { value: "classification", label: "Classification", activeLabel: "Classifying play" },
  { value: "report", label: "Report", activeLabel: "Building analysis" },
];
const PHASES = [
  { label: "Preparation", detail: "Media and court", start: 0, end: 1 },
  { label: "Read the play", detail: "Players, ball, and events", start: 2, end: 5 },
  { label: "Build the journal", detail: "Measures and evidence links", start: 6, end: 6 },
] as const;

const jobKey = (jobId: string) => ["jobs", jobId] as const;
const matchKey = (matchId: string) => ["matches", matchId] as const;
const TERMINAL_STATES: Record<string, true> = {
  completed: true,
  failed: true,
  cancelled: true,
};

function isTerminal(state: JobStatus | undefined): boolean {
  return state !== undefined && state in TERMINAL_STATES;
}

function matchTime(valueUs: number): string {
  const totalSeconds = Math.floor(valueUs / 1_000_000);
  const hours = Math.floor(totalSeconds / 3_600);
  const minutes = Math.floor((totalSeconds % 3_600) / 60);
  const seconds = totalSeconds % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function failureNextAction(code: string): string {
  if (code.includes("model")) return "Check local model readiness, install any missing model, then retry analysis.";
  if (code.includes("calibration")) return "Return to setup, save a valid calibration, then retry analysis.";
  return "Reload the durable snapshot, then retry analysis from verified inputs.";
}


function mutationPath(action: "pause" | "resume" | "cancel" | "retry") {
  const paths = {
    pause: "/api/v1/jobs/{job_id}/pause",
    resume: "/api/v1/jobs/{job_id}/resume",
    cancel: "/api/v1/jobs/{job_id}/cancel",
    retry: "/api/v1/jobs/{job_id}/retry",
  } as const;
  return paths[action];
}

function JobControl({
  job,
  action,
  label,
}: {
  job: JobDetail;
  action: "pause" | "resume" | "cancel" | "retry";
  label: string;
}) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => request(mutationPath(action), "post", {
      path: { job_id: job.id },
      decode: decodeJob,
    }),
    onSuccess: async (updated) => {
      queryClient.setQueryData<JobDetail>(jobKey(updated.id), (current) =>
        current === undefined || updated.version >= current.version ? updated : current,
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: matchKey(job.matchId) }),
        updated.id === job.id
          ? Promise.resolve()
          : queryClient.invalidateQueries({ queryKey: jobKey(updated.id) }),
      ]);
    },
  });

  return (
    <div className="control-with-error">
      <button
        type="button"
        className={action === "cancel" ? "button-danger" : action === "retry" ? "button-primary" : "button-secondary"}
        disabled={mutation.isPending}
        onClick={() => {
          if (action !== "cancel" || window.confirm("Cancel this analysis? Completed chunks will remain local.")) {
            mutation.mutate();
          }
        }}
      >
        {mutation.isPending ? `${label}…` : label}
      </button>
      {mutation.isError ? <span role="alert">{label} failed. Reload the job snapshot and try again.</span> : null}
    </div>
  );
}

function validControls(state: JobStatus): Array<"pause" | "resume" | "cancel" | "retry"> {
  if (state === "running") return ["pause", "cancel"];
  if (state === "queued") return ["cancel"];
  if (state === "paused") return ["resume", "cancel"];
  if (state === "failed" || state === "cancelled") return ["retry"];
  return [];
}

export function ProcessingView() {
  const { matchId = "" } = useParams();
  const queryClient = useQueryClient();
  const [streamError, setStreamError] = useState(false);
  const match = useQuery({
    queryKey: matchKey(matchId),
    enabled: matchId !== "",
    queryFn: ({ signal }) => request("/api/v1/matches/{match_id}", "get", {
      path: { match_id: matchId }, signal, decode: decodeMatchDetail,
    }),
  });
  const resolvedJobId = match.data?.latestJob?.id;
  const job = useQuery({
    queryKey: jobKey(resolvedJobId ?? "missing"),
    enabled: resolvedJobId !== undefined,
    initialData: match.data?.latestJob ?? undefined,
    queryFn: ({ signal }) => request("/api/v1/jobs/{job_id}", "get", {
      path: { job_id: resolvedJobId ?? "" }, signal, decode: decodeJob,
    }),
  });

  const terminalJob = isTerminal(job.data?.state);
  useEffect(() => {
    if (resolvedJobId === undefined || terminalJob) return;
    setStreamError(false);
    let closeStream = (): void => {};
    closeStream = streamJobEvents(resolvedJobId, {
      decode: decodeJobEvent,
      onSnapshot: (event) => {
        let accepted = false;
        queryClient.setQueryData<JobDetail>(jobKey(event.job.id), (current) => {
          if (current !== undefined && event.job.version <= current.version) return current;
          accepted = true;
          return event.job;
        });
        if (!accepted) return;
        setStreamError(false);
        void queryClient.invalidateQueries({ queryKey: matchKey(matchId) });
        if (isTerminal(event.job.state)) closeStream();
      },
      onError: () => setStreamError(true),
    });
    return closeStream;
  }, [matchId, queryClient, resolvedJobId, terminalJob]);

  if (match.isPending) {
    return <AppShell matchId={matchId} active="processing"><div className="processing-skeleton" aria-label="Loading processing state">Loading durable job snapshot…</div></AppShell>;
  }
  if (match.isError) {
    return <AppShell matchId={matchId} active="processing"><div role="alert" className="action-state"><h1>Processing state unavailable</h1><button type="button" onClick={() => void match.refetch()}>Retry match</button></div></AppShell>;
  }
  if (resolvedJobId === undefined || match.data.latestJob === null) {
    return <AppShell matchId={matchId} active="processing"><div className="action-state"><h1>No analysis job yet</h1><p>Finish calibration and choose a processing profile first.</p><Link className="button-primary" to={`/matches/${matchId}/setup`}>Return to setup</Link></div></AppShell>;
  }
  if (job.isError || job.data === undefined) {
    return <AppShell matchId={matchId} active="processing"><div role="alert" className="action-state"><h1>Job snapshot unavailable</h1><button type="button" onClick={() => void job.refetch()}>Reload job snapshot</button></div></AppShell>;
  }

  const snapshot = job.data;
  const progress = snapshot.progress;
  const hasRealProgress = progress !== null && progress.plannedChunks > 0;
  const fraction = hasRealProgress
    ? progress.completedChunks / progress.plannedChunks
    : null;
  const visualState = snapshot.state === "running" && snapshot.stage === "report" ? "finalizing" : snapshot.state;
  const stageDefinition = snapshot.stage === null
    ? null
    : STAGES.find((stage) => stage.value === snapshot.stage) ?? null;
  const controls = validControls(snapshot.state);
  const currentStageIndex = snapshot.stage === null
    ? -1
    : STAGES.findIndex((stage) => stage.value === snapshot.stage);
  const partialRevision = match.data.latestReport?.revision;
  const failedCode = snapshot.failureCode ?? "processing_failed";
  const currentRange = snapshot.currentRangeStartUs !== null && snapshot.currentRangeStartUs !== undefined
    && snapshot.currentRangeEndUs !== null && snapshot.currentRangeEndUs !== undefined
    ? `${matchTime(snapshot.currentRangeStartUs)}–${matchTime(snapshot.currentRangeEndUs)} match time`
    : null;

  return (
    <AppShell matchId={matchId} active="processing" stage={snapshot.stage} jobStatus={snapshot.state} progress={fraction}>
      <header className="page-heading processing-heading" data-state={visualState}>
        <div className="processing-heading-meta"><p className="kicker">{match.data.title}</p><span className={`state state-${visualState}`}>{visualState.replaceAll("_", " ")}</span></div>
        {snapshot.state === "failed"
          ? <h1>Analysis stopped safely</h1>
          : snapshot.state === "completed"
            ? <h1>Analysis complete</h1>
            : visualState === "finalizing"
              ? <h1>Finalizing analysis</h1>
              : snapshot.stage === null
                ? <h1>Waiting for worker</h1>
                : <h1>{stageDefinition?.activeLabel ?? "Processing match"}</h1>}
        <p>{snapshot.state === "completed" ? "Your match journal is ready to explore." : snapshot.state === "failed" ? "Your video and completed work are safe on this device." : visualState === "finalizing" ? "Measured sections are being assembled into an immutable report revision." : snapshot.state === "queued" ? "The job is queued locally. Progress begins only after a worker publishes a chunk plan." : "SquashVision is reading the match in measured passes. You can leave this page and return later."}</p>
      </header>
      <div className="processing-layout">
        <ol className="processing-overview" aria-label="Processing overview">
          {PHASES.map((phase) => {
            const phaseState = snapshot.state === "completed" || currentStageIndex > phase.end
              ? "complete"
              : currentStageIndex >= phase.start && currentStageIndex <= phase.end
                ? snapshot.state === "failed" ? "stopped" : "current"
                : "waiting";
            return (
              <li key={phase.label} data-state={phaseState} aria-current={phaseState === "current" ? "step" : undefined}>
                <strong>{phase.label}</strong>
                <span>{phase.detail}</span>
              </li>
            );
          })}
        </ol>
        <details className="stage-ledger processing-details">
          <summary>Stage information</summary>
          <p className="technical-id">Job {snapshot.id} · {snapshot.profile}</p>
          <ol aria-label="Analysis stages">
            {STAGES.map((stage, index) => {
              const currentIndex = currentStageIndex;
              const state = currentIndex < 0
                ? "waiting"
                : index < currentIndex
                  ? "complete"
                  : index === currentIndex
                    ? snapshot.stageState ?? snapshot.state
                    : "waiting";
              return <li key={stage.value} data-state={state}><span>{stage.label}</span><small>{String(state).replaceAll("_", " ")}</small></li>;
            })}
          </ol>
        </details>
        <section className="processing-instrument" data-state={visualState} aria-label="Current processing evidence">
          {snapshot.state === "failed" ? (
            <div className="failure-state">
              <p className="kicker">Safe error code</p>
              <code>{failedCode}</code>
              <p>{failureNextAction(failedCode)}</p>
            </div>
          ) : null}
          {snapshot.state === "cancelled" ? <p className="status-neutral">Analysis cancelled</p> : null}
          <div className="job-controls" aria-label="Processing controls">
            {controls.includes("pause") ? <JobControl job={snapshot} action="pause" label="Pause analysis" /> : null}
            {controls.includes("resume") ? <JobControl job={snapshot} action="resume" label="Resume analysis" /> : null}
            {controls.includes("cancel") ? <JobControl job={snapshot} action="cancel" label="Cancel analysis" /> : null}
            {controls.includes("retry") ? <JobControl job={snapshot} action="retry" label="Retry analysis" /> : null}
          </div>
          {hasRealProgress && progress !== null ? (
            <div className="real-progress" aria-live="polite">
              <progress max={100} value={Math.round((fraction ?? 0) * 100)} aria-label="Analysis progress" aria-valuenow={Math.round((fraction ?? 0) * 100)} />
              <strong>{progress.completedChunks} of {progress.plannedChunks} processing chunks complete</strong>
            </div>
          ) : <p>Waiting for the worker to publish a chunk plan. No progress estimate is available yet.</p>}
          <p className="processing-range">{currentRange ?? "Current match-time range is not planned yet."}</p>
          {snapshot.state === "running" || snapshot.state === "queued" ? <p className="quiet">You can close this tab. Keep SquashVision running until processing finishes.</p> : null}
          {match.data.quality.warnings.length > 0 ? (
            <div className="processing-warnings"><h2>Warnings</h2><ul>{match.data.quality.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>
          ) : null}
          {streamError ? (
            <div role="alert" className="stream-warning">
              <strong>Live updates interrupted</strong>
              <span>The browser will reconnect safely; reload the durable snapshot at any time.</span>
              <button type="button" className="button-secondary" onClick={() => {
                setStreamError(false);
                void job.refetch();
              }}>Reload job snapshot</button>
            </div>
          ) : null}
          {partialRevision !== undefined && snapshot.state !== "completed" ? (
            <Link className="button-secondary" to={`/matches/${matchId}/analysis?revision=${partialRevision}`}>Open partial analysis</Link>
          ) : null}
          {snapshot.state === "completed" ? <Link className="button-primary" to={`/matches/${matchId}/analysis`}>View analysis</Link> : null}
        </section>
      </div>
    </AppShell>
  );
}
