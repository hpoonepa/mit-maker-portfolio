import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { ApiError, request } from "../../api/client";
import {
  decodeCorrectionConflicts,
  decodeMatchDetail,
  decodeMatchReport,
  decodeTimelineItem,
} from "../../api/decoders";
import type { components } from "../../api/types.generated";
import { AppShell } from "../../components/AppShell";
import { CoachingReport } from "../reports/CoachingReport";
import { ErrorsReport } from "../reports/ErrorsReport";
import { HeadToHeadReport } from "../reports/HeadToHeadReport";
import { MovementReport } from "../reports/MovementReport";
import { OverviewReport } from "../reports/OverviewReport";
import { RalliesReport } from "../reports/RalliesReport";
import { ShotsReport } from "../reports/ShotsReport";
import { TrajectoryReport } from "../reports/TrajectoryReport";
import { numberValue, reportSection } from "../reports/report-model";
import { CorrectionEditor, ReapplicationConflictControls } from "../review/CorrectionEditor";
import { ReviewQueue } from "../review/ReviewQueue";
import type { ReviewShortcut } from "../review/ReviewQueue";
import { buildReviewQueue } from "../review/review-model";
import type { ReviewItem } from "../review/review-model";
import { IncompletePageError, allBallPages, allPlayerPages, allReportPages, allReviewPages, allTimelinePages, analysisKeys, revisionFromSearch } from "./analysis-data";
import { boundedObservationWindow, evidenceStep, formatMatchTime, isPlayableTimelineEvent, OBSERVATION_WINDOW_STEP_US, shouldIgnorePlaybackShortcut } from "./analysis-model";
import { EvidenceWorkspace } from "./EvidenceWorkspace";
import { ExportControls } from "./ExportControls";
import { MatchSummary } from "./TrackingStatsPanel";
import { PlaybackStatsPanel } from "./PlaybackStatsPanel";
import { usePlaybackTimeline } from "./playback-data";
import { ShotReviewPanel } from "./ShotReviewPanel";
import { LiveShotPanel } from "./LiveShotPanel";
import { useShotReview } from "./shot-review-data";
import { automaticShots, mergeShots } from "./shot-model";

type CorrectionCommand = components["schemas"]["CorrectionCommand"];
type CorrectionCommandType = components["schemas"]["CorrectionCommandType"];
type ConflictResolution = components["schemas"]["ConflictResolution"];
type TimelineItem = components["schemas"]["TimelineItem"];

type ReportTab = "overview" | "shots" | "rallies" | "movement" | "errors" | "trajectory" | "head-to-head" | "coaching";

const REPORT_TABS: Array<{ id: ReportTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "shots", label: "Shots" },
  { id: "rallies", label: "Rallies" },
  { id: "movement", label: "Movement" },
  { id: "errors", label: "Errors" },
  { id: "trajectory", label: "Trajectory" },
  { id: "head-to-head", label: "Head-to-head" },
  { id: "coaching", label: "Coaching" },
];
const REPORT_GROUPS: Array<{ label: string; tabs: ReportTab[] }> = [
  { label: "Summary", tabs: ["overview"] },
  { label: "Evidence", tabs: ["shots", "rallies", "errors"] },
  { label: "Movement", tabs: ["movement", "trajectory", "head-to-head"] },
  { label: "Review", tabs: ["coaching"] },
];

function evidenceTitle(item: TimelineItem | null): string {
  if (item === null) return "No event selected";
  if (item.kind === "rally") return "Rally evidence";
  if (item.kind === "shot") return "Shot evidence";
  if (item.kind.includes("error") || item.kind === "review") return "Review this decision";
  if (item.kind.includes("confidence") || item.kind === "reconstruction") return "Check evidence confidence";
  return "Selected match evidence";
}


type ReportSummary = components["schemas"]["ReportSummary"];
const EMPTY_REVIEW_ITEMS: ReviewItem[] = [];

export function AnalysisWorkspace() {
  const { matchId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const videoRef = useRef<HTMLVideoElement>(null);
  const selectedStatusRef = useRef<HTMLOutputElement>(null);
  const [overlayControlsElement, setOverlayControlsElement] = useState<HTMLDivElement | null>(null);
  const pinnedRevision = revisionFromSearch(searchParams.get("revision"));
  const [currentTimeUs, setCurrentTimeUs] = useState(0);
  const initialSeekApplied = useRef(false);
  const [playing, setPlaying] = useState(false);
  const [playbackError, setPlaybackError] = useState<string | null>(null);
  const [videoSize, setVideoSize] = useState({ width: 1920, height: 1080 });
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ReportTab>("overview");
  const [reviewIndex, setReviewIndex] = useState(0);
  const [shortcut, setShortcut] = useState<{ version: number; command: ReviewShortcut } | null>(null);
  const [conflictRevision, setConflictRevision] = useState<number | null>(null);
  const [nearestStep, setNearestStep] = useState(false);
  const [draftCommandType, setDraftCommandType] = useState<CorrectionCommandType>("accept");
  const [playbackRate, setPlaybackRate] = useState(1);
  const [shotEditingReport, setShotEditingReport] = useState<components["schemas"]["MatchReport"] | null>(null);

  const match = useQuery({
    queryKey: analysisKeys.match(matchId), enabled: matchId !== "", queryFn: ({ signal }) => request("/api/v1/matches/{match_id}", "get", { path: { match_id: matchId }, signal, decode: decodeMatchDetail }),
  });
  const hasPublishedReport = match.data?.latestReport !== null
    && match.data?.latestReport !== undefined;
  useEffect(() => {
    if (match.data?.latestReport !== null || pinnedRevision === null) return;
    const next = new URLSearchParams(searchParams);
    next.delete("revision");
    setSearchParams(next, { replace: true });
  }, [match.data?.latestReport, pinnedRevision, searchParams, setSearchParams]);
  const history = useQuery({
    queryKey: analysisKeys.reports(matchId), enabled: matchId !== "" && hasPublishedReport, queryFn: ({ signal }) => allReportPages(matchId, signal),
  });
  const latestReport = useQuery({
    queryKey: analysisKeys.latestReport(matchId), enabled: matchId !== "" && hasPublishedReport && pinnedRevision === null, queryFn: ({ signal }) => request("/api/v1/matches/{match_id}/reports/latest", "get", { path: { match_id: matchId }, signal, decode: decodeMatchReport }),
  });
  const historicalReport = useQuery({
    queryKey: analysisKeys.report(matchId, pinnedRevision ?? 0), enabled: matchId !== "" && hasPublishedReport && pinnedRevision !== null, queryFn: ({ signal }) => request("/api/v1/matches/{match_id}/reports/{revision}", "get", { path: { match_id: matchId, revision: pinnedRevision ?? 0 }, signal, decode: decodeMatchReport }),
  });
  const selectedReport = hasPublishedReport
    ? shotEditingReport ?? (pinnedRevision === null ? latestReport.data : historicalReport.data)
    : undefined;
  const handleShotDirtyChange = useCallback((dirty: boolean) => {
    setShotEditingReport(dirty ? selectedReport ?? null : null);
  }, [selectedReport]);
  const durationUs = match.data?.assets.find((asset) => asset.kind === "proxy")?.durationUs ?? 0;
  const windowRange = boundedObservationWindow(currentTimeUs, durationUs);
  const nextWindowRange = boundedObservationWindow(currentTimeUs + OBSERVATION_WINDOW_STEP_US, durationUs);
  const reportRevision = selectedReport?.revision ?? 0;
  const jobId = match.data?.latestJob?.id ?? "no-job";
  const timelineKinds = "rally,shot,error,contact,observationWindow";
  const authoritativeConflictRevision = conflictRevision ?? Math.max(reportRevision, match.data?.latestReport?.revision ?? 0);
  const canRetainEvidence = (key: readonly unknown[] | undefined): boolean => key !== undefined
    && key[1] === matchId && key[4] === reportRevision && key[5] === jobId
    && typeof key[6] === "number" && typeof key[7] === "number"
    && currentTimeUs >= key[6] && currentTimeUs < key[7];

  const timeline = useQuery({
    queryKey: analysisKeys.timeline(matchId, reportRevision, jobId, windowRange.startUs, windowRange.endUs, timelineKinds),
    enabled: matchId !== "" && selectedReport !== undefined && windowRange.endUs > windowRange.startUs,
    queryFn: ({ signal }) => allTimelinePages(matchId, reportRevision, windowRange.startUs, windowRange.endUs, timelineKinds, signal),
    staleTime: 60_000,
    placeholderData: (previous, query) => canRetainEvidence(query?.queryKey) ? previous : undefined,
  });
  const players = useQuery({
    queryKey: analysisKeys.observations(matchId, reportRevision, jobId, "players", windowRange.startUs, windowRange.endUs),
    enabled: matchId !== "" && selectedReport !== undefined && windowRange.endUs > windowRange.startUs,
    queryFn: ({ signal }) => allPlayerPages(matchId, reportRevision, windowRange.startUs, windowRange.endUs, signal),
    staleTime: 60_000,
    placeholderData: (previous, query) => canRetainEvidence(query?.queryKey) ? previous : undefined,
  });
  const balls = useQuery({
    queryKey: analysisKeys.observations(matchId, reportRevision, jobId, "ball", windowRange.startUs, windowRange.endUs),
    enabled: matchId !== "" && selectedReport !== undefined && windowRange.endUs > windowRange.startUs,
    queryFn: ({ signal }) => allBallPages(matchId, reportRevision, windowRange.startUs, windowRange.endUs, signal),
    staleTime: 60_000,
    placeholderData: (previous, query) => canRetainEvidence(query?.queryKey) ? previous : undefined,
  });
  const serverReview = useQuery({
    queryKey: analysisKeys.review(matchId, reportRevision),
    enabled: matchId !== "" && reportRevision > 0,
    queryFn: ({ signal }) => allReviewPages(matchId, reportRevision, signal),
  });
  const conflicts = useQuery({
    queryKey: analysisKeys.conflicts(matchId, authoritativeConflictRevision),
    enabled: matchId !== "" && authoritativeConflictRevision > 0,
    queryFn: ({ signal }) => request("/api/v1/matches/{match_id}/correction-conflicts", "get", { path: { match_id: matchId }, signal, decode: decodeCorrectionConflicts }),
  });
  const conflictReport = useQuery({
    queryKey: analysisKeys.report(matchId, authoritativeConflictRevision),
    enabled: matchId !== "" && authoritativeConflictRevision > 0 && authoritativeConflictRevision !== reportRevision,
    queryFn: ({ signal }) => request("/api/v1/matches/{match_id}/reports/{revision}", "get", { path: { match_id: matchId, revision: authoritativeConflictRevision }, signal, decode: decodeMatchReport }),
  });
  useEffect(() => {
    if (typeof window.requestIdleCallback !== "function" || reportRevision === 0) return;
    const adjacentStartUs = nextWindowRange.startUs;
    const adjacentEndUs = nextWindowRange.endUs;
    if (adjacentEndUs <= adjacentStartUs) return;
    if (adjacentStartUs === windowRange.startUs && adjacentEndUs === windowRange.endUs) return;
    const idleId = window.requestIdleCallback(() => {
      void Promise.all([
        queryClient.prefetchQuery({
          queryKey: analysisKeys.timeline(matchId, reportRevision, jobId, adjacentStartUs, adjacentEndUs, timelineKinds),
          queryFn: ({ signal }) => allTimelinePages(matchId, reportRevision, adjacentStartUs, adjacentEndUs, timelineKinds, signal),
          staleTime: 60_000,
        }),
        queryClient.prefetchQuery({
          queryKey: analysisKeys.observations(matchId, reportRevision, jobId, "players", adjacentStartUs, adjacentEndUs),
          queryFn: ({ signal }) => allPlayerPages(matchId, reportRevision, adjacentStartUs, adjacentEndUs, signal),
          staleTime: 60_000,
        }),
        queryClient.prefetchQuery({
          queryKey: analysisKeys.observations(matchId, reportRevision, jobId, "ball", adjacentStartUs, adjacentEndUs),
          queryFn: ({ signal }) => allBallPages(matchId, reportRevision, adjacentStartUs, adjacentEndUs, signal),
          staleTime: 60_000,
        }),
      ]);
    }, { timeout: 1_000 });
    return () => window.cancelIdleCallback(idleId);
  }, [jobId, matchId, nextWindowRange.endUs, nextWindowRange.startUs, queryClient, reportRevision, timelineKinds, windowRange.endUs, windowRange.startUs]);
  const partialHistoryItems = history.error instanceof IncompletePageError ? history.error.items as ReportSummary[] : [];
  const historyItems = history.data?.items ?? partialHistoryItems;
  const loadedConflictRevision = authoritativeConflictRevision === reportRevision ? reportRevision : conflictReport.data?.revision === authoritativeConflictRevision ? authoritativeConflictRevision : null;
  const events = useMemo(() => (timeline.data?.items ?? []).filter(isPlayableTimelineEvent), [timeline.data?.items]);
  const evidenceLoading = reportRevision > 0 && (timeline.isPending || players.isPending || balls.isPending || timeline.isPlaceholderData || players.isPlaceholderData || balls.isPlaceholderData);
  const evidenceTimestamps = useMemo(() => events.map((item) => item.timestampUs).concat((players.data ?? []).map((item) => item.sourceTimestampUs ?? item.timestampUs), (balls.data ?? []).map((item) => item.sourceTimestampUs ?? item.timestampUs)), [balls.data, events, players.data]);
  const partialReviewItems = serverReview.error instanceof IncompletePageError ? serverReview.error.items as ReviewItem[] : EMPTY_REVIEW_ITEMS;
  const reviewItems = useMemo(() => buildReviewQueue(serverReview.data ?? partialReviewItems, serverReview.isSuccess ? events : []), [events, partialReviewItems, serverReview.data, serverReview.isSuccess]);
  const reviewSection = selectedReport === undefined ? null : reportSection(selectedReport, "review");
  const reviewedCount = reviewSection === null ? 0 : numberValue(reviewSection.payload, "reviewed_count") ?? 0;
  const totalReviewCount = reviewSection === null ? reviewItems.length : numberValue(reviewSection.payload, "candidate_count") ?? reviewItems.length;
  const selectedEvent = selectedEventId === null ? null : events.find((item) => item.id === selectedEventId) ?? null;
  const currentReview = reviewItems[reviewIndex] ?? reviewItems[0] ?? null;

  useEffect(() => {
    if (reviewIndex >= reviewItems.length) setReviewIndex(Math.max(0, reviewItems.length - 1));
  }, [reviewIndex, reviewItems.length]);
  useEffect(() => {
    setSelectedEventId(null);
    setNearestStep(false);
  }, [reportRevision]);

  const seekToEvidence = useCallback((timestampUs: number, eventId: string | null, focusStatus = true): void => {
    const bounded = Math.max(0, Math.min(Math.max(0, durationUs - 1), timestampUs));
    setCurrentTimeUs(bounded);
    setSelectedEventId(eventId);
    if (videoRef.current !== null) videoRef.current.currentTime = bounded / 1_000_000;
    if (focusStatus) window.requestAnimationFrame(() => selectedStatusRef.current?.focus({ preventScroll: true }));
  }, [durationUs]);

  // Integer-microsecond timestamps can round just before a 30fps frame edge.
  // Seek one microsecond inside it; presented-frame callbacks set the UI clock.
  const seekTrackingContact = useCallback((timestampUs: number) => seekToEvidence(timestampUs + 1, null, false), [seekToEvidence]);
  const playback = usePlaybackTimeline(matchId, reportRevision, currentTimeUs, match.data?.calibrationRevision ?? null);
  const shotReview = useShotReview(matchId, reportRevision);
  const playbackShots = useMemo(() => shotReview.query.isSuccess ? mergeShots(automaticShots(playback.data, shotReview.query.data.wallCalibration), shotReview.query.data.shots) : [], [playback.data, shotReview.query.data, shotReview.query.isSuccess]);

  const togglePlayback = useCallback(async (): Promise<void> => {
    const video = videoRef.current;
    if (video === null) return;
    setPlaybackError(null);
    if (!video.paused) {
      video.pause();
      return;
    }
    try {
      await video.play();
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setPlaying(false);
      setPlaybackError("Playback could not start. Press Play to try again, or reload the video.");
    }
  }, []);

  const evidenceLookup = useMutation({
    mutationFn: ({ evidenceId, revision }: { evidenceId: string; revision: number }) => request("/api/v1/matches/{match_id}/evidence/{evidence_id}", "get", {
      path: { match_id: matchId, evidence_id: evidenceId },
      query: { revision },
      decode: decodeTimelineItem,
    }),
    onSuccess: (item, variables) => {
      if (variables.revision === reportRevision) seekToEvidence(item.timestampUs, isPlayableTimelineEvent(item) ? item.id ?? null : null);
    },
  });

  const seekEvidenceId = useCallback((evidenceId: string): void => {
    const event = events.find((item) => item.id === evidenceId || item.evidenceIds?.includes(evidenceId));
    if (event !== undefined) {
      seekToEvidence(event.timestampUs, event.id ?? null);
      return;
    }
    evidenceLookup.mutate({ evidenceId, revision: reportRevision });
  }, [events, evidenceLookup, reportRevision, seekToEvidence]);

  const stepEvidence = useCallback((direction: -1 | 1): void => {
    const step = evidenceStep(evidenceTimestamps, currentTimeUs, direction);
    if (step === null) return;
    setNearestStep(!step.exact);
    seekToEvidence(step.timestampUs, events.find((item) => item.timestampUs === step.timestampUs)?.id ?? null);
  }, [currentTimeUs, events, evidenceTimestamps, seekToEvidence]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent): void => {
      if (event.defaultPrevented || shouldIgnorePlaybackShortcut(event.target)) return;
      if (event.key === "[" || event.key === "]") {
        event.preventDefault();
        const ordered = [...events].sort((left, right) => left.timestampUs - right.timestampUs);
        const currentIndex = ordered.findIndex((item) => item.id === selectedEventId);
        const nextIndex = event.key === "]" ? Math.min(ordered.length - 1, currentIndex + 1) : Math.max(0, currentIndex <= 0 ? 0 : currentIndex - 1);
        const item = ordered[nextIndex];
        if (item !== undefined) seekToEvidence(item.timestampUs, item.id ?? null);
      } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        stepEvidence(event.key === "ArrowRight" ? 1 : -1);
      } else if (event.code === "Space") {
        event.preventDefault();
        void togglePlayback();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [events, seekToEvidence, selectedEventId, stepEvidence, togglePlayback]);

  const updatePinnedRevision = (revision: number): void => {
    const next = new URLSearchParams(searchParams);
    next.set("revision", String(revision));
    setSearchParams(next, { replace: true });
  };

  const correction = useMutation({
    mutationFn: (command: CorrectionCommand) => request("/api/v1/matches/{match_id}/corrections", "post", { path: { match_id: matchId }, body: command, decode: decodeMatchReport }),
    onSuccess: async (nextReport) => {
      const preservedTime = videoRef.current?.currentTime ?? currentTimeUs / 1_000_000;
      queryClient.setQueryData(analysisKeys.report(matchId, nextReport.revision), nextReport);
      updatePinnedRevision(nextReport.revision);
      setConflictRevision(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: analysisKeys.reports(matchId) }),
        queryClient.invalidateQueries({ queryKey: ["matches", matchId, "analysis", "timeline"] }),
        queryClient.invalidateQueries({ queryKey: ["matches", matchId, "analysis", "observations"] }),
        queryClient.invalidateQueries({ queryKey: analysisKeys.review(matchId, nextReport.revision) }),
      ]);
      if (videoRef.current !== null) videoRef.current.currentTime = preservedTime;
    },
    onError: (error) => {
      if (!(error instanceof ApiError) || error.status !== 409) return;
      const currentRevision = error.details?.currentRevision;
      setConflictRevision(typeof currentRevision === "number" && Number.isSafeInteger(currentRevision) ? currentRevision : (historyItems[0]?.revision ?? reportRevision));
    },
  });

  const resolveConflict = useMutation({
    mutationFn: ({ correctionId, body }: { correctionId: string; body: ConflictResolution }) => request("/api/v1/matches/{match_id}/correction-conflicts/{correction_id}/resolve", "post", { path: { match_id: matchId, correction_id: correctionId }, body, decode: decodeMatchReport }),
    onSuccess: async (nextReport) => {
      const preservedTime = videoRef.current?.currentTime ?? currentTimeUs / 1_000_000;
      queryClient.setQueryData(analysisKeys.report(matchId, nextReport.revision), nextReport);
      updatePinnedRevision(nextReport.revision);
      setConflictRevision(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: analysisKeys.reports(matchId) }),
        queryClient.invalidateQueries({ queryKey: analysisKeys.conflicts(matchId) }),
        queryClient.invalidateQueries({ queryKey: ["matches", matchId, "analysis", "timeline"] }),
        queryClient.invalidateQueries({ queryKey: ["matches", matchId, "analysis", "observations"] }),
        queryClient.invalidateQueries({ queryKey: analysisKeys.review(matchId, nextReport.revision) }),
      ]);
      if (videoRef.current !== null) videoRef.current.currentTime = preservedTime;
    },
    onError: (error) => {
      if (!(error instanceof ApiError) || error.status !== 409) return;
      const currentRevision = error.details?.currentRevision;
      if (typeof currentRevision === "number" && Number.isSafeInteger(currentRevision)) setConflictRevision(currentRevision);
    },
  });

  const resolveLoadedConflict = (correctionId: string, candidateId: string | null, resolution: "select" | "reject"): void => {
    if (loadedConflictRevision === null || resolveConflict.isPending) return;
    resolveConflict.mutate({
      correctionId,
      body: {
        candidateId,
        expectedReportRevision: loadedConflictRevision,
        reason: resolution === "select" ? "Selected matching evidence after reapplication review" : "Rejected reapplication after evidence review",
        resolution,
      },
    });
  };

  const reportPanel = selectedReport === undefined ? null : activeTab === "overview" ? <OverviewReport report={selectedReport} onSeekEvidence={seekEvidenceId} />
    : activeTab === "shots" ? <ShotsReport report={selectedReport} onSeekEvidence={seekEvidenceId} />
      : activeTab === "rallies" ? <RalliesReport report={selectedReport} matchId={matchId} durationUs={durationUs} onSeekEvidence={seekEvidenceId} />
        : activeTab === "movement" ? <MovementReport report={selectedReport} onSeekEvidence={seekEvidenceId} />
          : activeTab === "errors" ? <ErrorsReport report={selectedReport} onSeekEvidence={seekEvidenceId} />
            : activeTab === "trajectory" ? <TrajectoryReport report={selectedReport} onSeekEvidence={seekEvidenceId} />
              : activeTab === "head-to-head" ? <HeadToHeadReport report={selectedReport} onSeekEvidence={seekEvidenceId} />
                : <CoachingReport report={selectedReport} onSeekEvidence={seekEvidenceId} />;

  const handleTabKey = (event: ReactKeyboardEvent<HTMLButtonElement>, index: number): void => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft" && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? REPORT_TABS.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + REPORT_TABS.length) % REPORT_TABS.length;
    setActiveTab(REPORT_TABS[nextIndex].id);
    document.getElementById(`report-tab-${REPORT_TABS[nextIndex].id}`)?.focus();
  };

  const selectedReportPending = hasPublishedReport && shotEditingReport === null && (pinnedRevision === null ? latestReport.isPending : historicalReport.isPending);
  const selectedReportError = hasPublishedReport && shotEditingReport === null && (pinnedRevision === null ? latestReport.isError : historicalReport.isError);
  if (match.isPending || (hasPublishedReport && history.isPending) || selectedReportPending) return <AppShell matchId={matchId} active="analysis"><div className="analysis-skeleton" aria-label="Loading analysis workspace">Loading analysis…</div></AppShell>;
  if (hasPublishedReport && history.isError && historyItems.length === 0) return <AppShell matchId={matchId} active="analysis"><div className="action-state" role="alert"><h1>Report history unavailable</h1><p>Report history could not be loaded.</p><button type="button" disabled={history.isFetching} onClick={() => void history.refetch()}>{history.isFetching ? "Retrying report history…" : "Retry report history"}</button></div></AppShell>;
  if (match.isError || selectedReportError || selectedReport === undefined) return <AppShell matchId={matchId} active="analysis"><div className="action-state" role="alert"><h1>Analysis unavailable</h1><p>Finish setup and processing to view the analysis.</p><div className="action-links"><Link className="button-secondary" to={`/matches/${matchId}/setup`}>Open setup</Link><Link className="button-primary" to={`/matches/${matchId}/processing`}>Open processing</Link></div></div></AppShell>;

  return (
    <AppShell matchId={matchId} active="analysis" stage={match.data.latestJob?.stage ?? null} jobStatus={match.data.latestJob?.state ?? null} progress={match.data.latestJob?.progress?.fraction ?? null}>
      <div className="analysis-workspace">
        <header className="analysis-header">
          <div><h1>{match.data.title}</h1><p><span className="player-a-mark">A</span>{match.data.metadata.playerOne ?? "Player A"}<span className="player-b-mark">B</span>{match.data.metadata.playerTwo ?? "Player B"}</p></div>
        </header>
        {history.isError ? <div className="status-error" role="alert"><strong>Report history incomplete</strong><p>{historyItems.length} revisions loaded. The selected report is available. Retry to load the rest of the history.</p><button type="button" disabled={history.isFetching} onClick={() => void history.refetch()}>{history.isFetching ? "Retrying report history…" : "Retry report history"}</button></div> : null}
        <EvidenceWorkspace
          matchId={matchId}
          reportRevision={reportRevision}
          evidenceLoading={evidenceLoading}
          currentTimeUs={currentTimeUs}
          durationUs={durationUs}
          playing={playing}
          playbackError={playbackError}
          playbackRate={playbackRate}
          nearestStep={nearestStep}
          videoSize={videoSize}
          videoRef={videoRef}
          selectedStatusRef={selectedStatusRef}
          players={players.data ?? []}
          balls={balls.data ?? []}
          events={events}
          windowRange={windowRange}
          selectedEvent={selectedEvent}
          selectedEventId={selectedEventId}
          overlayControlsElement={overlayControlsElement}
          setOverlayControlsElement={setOverlayControlsElement}
          onLoadedMetadata={(width, height) => {
            setVideoSize({ width, height });
            const seconds=Number(searchParams.get("t"));
            if(!initialSeekApplied.current&&Number.isFinite(seconds)&&seconds>0&&seconds*1e6<durationUs){seekTrackingContact(Math.round(seconds*1e6));}
            initialSeekApplied.current=true;
          }}
          onTimeUpdate={setCurrentTimeUs}
          onRateChange={setPlaybackRate}
          onPlayingChange={setPlaying}
          onPlaybackError={setPlaybackError}
          onTogglePlayback={() => void togglePlayback()}
          onStepEvidence={stepEvidence}
          onSeekTimeline={seekToEvidence}
          onScrub={(timestampUs) => { setNearestStep(false); seekToEvidence(timestampUs, null, false); }}
          impactMarker={playback.snapshot?.impactMarker ?? null}
          statsSidecar={<><LiveShotPanel matchId={matchId} reportRevision={reportRevision} timeline={playback.data} currentTimeUs={currentTimeUs} onSeek={us=>{videoRef.current?.pause();seekTrackingContact(us);}}/><PlaybackStatsPanel tinHeightM={shotReview.query.data?.wallCalibration?.tinHeightM} shots={playbackShots} data={playback.data} snapshot={playback.snapshot} currentTimeUs={currentTimeUs} loading={playback.loading || shotReview.query.isPending} error={playback.error || shotReview.query.isError} onRetry={()=>{playback.retry();void shotReview.query.refetch();}} onSeek={seekTrackingContact} /></>}
          inspector={(
            <>
              <section className="selected-evidence">
                
                <h2>{evidenceTitle(selectedEvent)}</h2>
                <p>{selectedEvent === null ? "Choose a moment from the timeline or reports." : formatMatchTime(selectedEvent.timestampUs, true)}</p>
                {selectedEvent === null ? null : (
                  <details className="review-technical">
                    <summary>Source details</summary>
                    <dl className="review-detail-ledger">
                      <div><dt>Event type</dt><dd>{selectedEvent.kind.replaceAll("_", " ")}</dd></div>
                      <div><dt>Evidence ID</dt><dd className="mono">{selectedEvent.id ?? "Not published"}</dd></div>
                    </dl>
                  </details>
                )}
              </section>
              {serverReview.isPending ? <div className="status-neutral" role="status">Loading complete review queue…</div> : null}
              {serverReview.isError ? <div className="status-error" role="alert"><strong>{partialReviewItems.length === 0 ? "Review queue unavailable" : "Review queue incomplete"}</strong><p>{partialReviewItems.length === 0 ? "No review items could be loaded." : `${partialReviewItems.length} review ${partialReviewItems.length === 1 ? "item" : "items"} loaded before the request failed.`} Load the remaining items to see the complete review queue.</p><button type="button" disabled={serverReview.isFetching} onClick={() => void serverReview.refetch()}>{serverReview.isFetching ? "Retrying review queue…" : "Retry review queue"}</button></div> : null}
              {serverReview.isSuccess || partialReviewItems.length > 0 ? <ReviewQueue items={reviewItems} currentIndex={reviewIndex} reviewedCount={reviewedCount} totalCount={totalReviewCount} activeImpact={currentReview?.commandImpacts[draftCommandType] ?? null} onNavigate={(index) => { const bounded = Math.max(0, Math.min(reviewItems.length - 1, index)); setReviewIndex(bounded); const item = reviewItems[bounded]; if (item !== undefined) seekToEvidence(item.timestampUs, item.id); }} onSeek={seekToEvidence} onShortcut={(command) => setShortcut((current) => ({ version: (current?.version ?? 0) + 1, command }))} /> : null}
              {conflictReport.isError && (conflictRevision !== null || (conflicts.isSuccess && conflicts.data.conflicts.length > 0)) ? <div className="status-error" role="alert"><strong>{conflictRevision === null ? "Conflict review partially loaded" : "Current conflict revision unavailable"}</strong><p>{conflictRevision === null ? `${conflicts.data?.conflicts.length ?? 0} conflict${conflicts.data?.conflicts.length === 1 ? "" : "s"} loaded, but resolution controls remain unavailable until current revision ${authoritativeConflictRevision} loads.` : `Resolution controls remain unavailable until revision ${authoritativeConflictRevision} is loaded.`}</p><button type="button" disabled={conflictReport.isFetching} onClick={() => void conflictReport.refetch()}>{conflictReport.isFetching ? "Retrying current revision…" : "Retry current revision"}</button></div> : null}
              {conflictRevision !== null && !conflictReport.isError ? <p className="conflict-comparison mono">{loadedConflictRevision === null ? `Loading revision ${authoritativeConflictRevision} alongside local draft…` : `Revision ${loadedConflictRevision} loaded alongside local draft for comparison.`}</p> : null}
              {conflicts.isPending ? <p className="status-neutral" role="status">Loading conflict candidates…</p> : null}
              {conflicts.isError ? <div className="status-error" role="alert"><strong>Conflict candidates unavailable</strong><p>The conflict list could not be loaded. Retry to review and resolve corrections.</p><button type="button" disabled={conflicts.isFetching} onClick={() => void conflicts.refetch()}>{conflicts.isFetching ? "Retrying conflict candidates…" : "Retry conflict candidates"}</button></div> : null}
              {loadedConflictRevision !== null && conflicts.isSuccess && conflicts.data.conflicts.length === 0 ? <output className="sr-only" aria-live="polite">No reapplication conflicts for current revision {loadedConflictRevision}.</output> : null}
              {loadedConflictRevision !== null && loadedConflictRevision !== reportRevision && conflicts.isSuccess && conflicts.data.conflicts.length > 0 ? <div className="correction-conflict" role="status"><strong>Reapplication conflicts belong to current revision {loadedConflictRevision}</strong><p>Your selected revision and draft will stay unchanged until you choose how to resolve the conflict.</p><button type="button" onClick={() => updatePinnedRevision(loadedConflictRevision)}>Rebase conflict review onto revision {loadedConflictRevision}</button></div> : null}
              {correction.isError && (!(correction.error instanceof ApiError) || correction.error.status !== 409) ? <div className="correction-conflict" role="alert"><strong>Correction was not saved</strong><p>{correction.error instanceof ApiError ? correction.error.message : "This correction could not be saved. Review the draft and retry."}</p><button type="button" disabled={correction.isPending || correction.variables === undefined} onClick={() => { if (correction.variables !== undefined) correction.mutate(correction.variables); }}>Retry correction</button></div> : null}
              {resolveConflict.isPending ? <p className="pending-label" role="status">Saving conflict resolution…</p> : null}
              {resolveConflict.isError ? <div className="correction-conflict" role="alert"><strong>Conflict resolution was not saved</strong><p>The current candidate selection and correction draft are retained.</p><button type="button" disabled={resolveConflict.isPending || resolveConflict.variables === undefined || loadedConflictRevision === null} onClick={() => { const variables = resolveConflict.variables; if (variables !== undefined && loadedConflictRevision !== null) resolveConflict.mutate({ ...variables, body: { ...variables.body, expectedReportRevision: loadedConflictRevision } }); }}>Retry conflict resolution</button></div> : null}
              {currentReview === null && loadedConflictRevision !== null && conflicts.isSuccess && conflicts.data.conflicts.length > 0 ? <section className="correction-editor" aria-labelledby="reapplication-conflicts-title"><h2 id="reapplication-conflicts-title">Resolve reanalysis conflicts</h2><ReapplicationConflictControls conflicts={conflicts.data.conflicts} pending={resolveConflict.isPending} onSeekConflictEvidence={(timestampUs, evidenceId) => seekToEvidence(timestampUs, evidenceId)} onResolveConflict={resolveLoadedConflict} /></section> : null}
              {currentReview === null ? null : <CorrectionEditor matchId={matchId} item={currentReview} reportRevision={selectedReport.revision} pending={correction.isPending} conflictRevision={conflictRevision} conflictResolutionPending={resolveConflict.isPending} shortcut={shortcut} reapplicationConflicts={loadedConflictRevision !== null && conflicts.isSuccess ? conflicts.data.conflicts : []} onSubmit={(command) => correction.mutate(command)} onCommandChange={setDraftCommandType} onRebase={() => { if (conflictRevision !== null) updatePinnedRevision(conflictRevision); }} onDiscard={() => setConflictRevision(null)} onSeekConflictEvidence={(timestampUs, evidenceId) => seekToEvidence(timestampUs, evidenceId)} onResolveConflict={resolveLoadedConflict} />}
            </>
          )}
        />
        <details className="shot-review-tools"><summary>Edit shot markers</summary><ShotReviewPanel key={`${matchId}:${reportRevision}`} matchId={matchId} reportRevision={reportRevision} timeline={playback.data} currentTimeUs={currentTimeUs} durationUs={durationUs} videoRef={videoRef} onSeek={seekTrackingContact} onDirtyChange={handleShotDirtyChange} /></details>
        <MatchSummary key={matchId} matchId={matchId} reportRevision={selectedReport.revision} onSeekVideo={seekTrackingContact} />
        <section className="reports-workspace" aria-label="Match report workspace">
          <header className="reports-heading">
            <h2>Match reports</h2>
          </header>
          <label className="report-mobile-picker">
            <span>Report section</span>
            <select aria-label="Report section" value={activeTab} onChange={(event) => setActiveTab(event.currentTarget.value as ReportTab)}>
              {REPORT_GROUPS.map((group) => (
                <optgroup key={group.label} label={group.label}>
                  {group.tabs.map((id) => {
                    const tab = REPORT_TABS.find((candidate) => candidate.id === id);
                    return tab === undefined ? null : <option key={id} value={id}>{tab.label}</option>;
                  })}
                </optgroup>
              ))}
            </select>
          </label>
          <div className="report-tabs" role="tablist" aria-label="Analysis reports">{REPORT_TABS.map((tab, index) => <button key={tab.id} id={`report-tab-${tab.id}`} type="button" role="tab" aria-selected={activeTab === tab.id} aria-controls={`report-panel-${tab.id}`} tabIndex={activeTab === tab.id ? 0 : -1} onClick={() => setActiveTab(tab.id)} onKeyDown={(event) => handleTabKey(event, index)}>{tab.label}</button>)}</div>
          <div id={`report-panel-${activeTab}`} className="report-panel" role="tabpanel" aria-labelledby={`report-tab-${activeTab}`} tabIndex={0}>{reportPanel}</div>
          {evidenceLookup.isError ? <div className="status-error" role="alert">This video moment is unavailable in report revision {selectedReport.revision}. Select another event or revision.</div> : null}
        </section>
        <ExportControls key={selectedReport.revision} matchId={matchId} report={selectedReport} />
      </div>
    </AppShell>
  );
}
