import { type InfiniteData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { request } from "../../api/client";
import { decodeJob, decodeMatchDetail } from "../../api/decoders";
import type { MatchListPage, MatchSummary } from "../../api/decoders";

interface MatchCardProps {
  match: MatchSummary;
  featured?: boolean;
  onDeleted: (matchId: string) => void;
}

const matchesKey = ["matches"] as const;
const detailKey = (matchId: string) => ["matches", matchId] as const;

function durationLabel(durationUs: number | null | undefined): string {
  if (durationUs === null || durationUs === undefined) return "Duration unavailable";
  const seconds = Math.floor(durationUs / 1_000_000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function processingLabel(match: MatchSummary): string {
  if (match.processing.state === "failed") {
    return `Failed${match.processing.stage === null || match.processing.stage === undefined ? "" : ` at ${match.processing.stage}`}`;
  }
  if (match.processing.state === "not_started") return "Ready to set up";
  if (match.processing.state === "running") return "Analyzing";
  if (match.processing.state === "completed") return "Analysis complete";
  return warningLabel(match.processing.state);
}
function warningLabel(value: string): string {
  const normalized = value.replaceAll("_", " ");
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

export function MatchCard({ match, featured = false, onDeleted }: MatchCardProps) {
  const queryClient = useQueryClient();
  const [previewReady, setPreviewReady] = useState(false);
  const [previewUnavailable, setPreviewUnavailable] = useState(false);
  const navigate = useNavigate();
  const detail = useQuery({
    queryKey: detailKey(match.id),
    queryFn: ({ signal }) => request("/api/v1/matches/{match_id}", "get", {
      path: { match_id: match.id },
      signal,
      decode: decodeMatchDetail,
    }),
  });
  const deleteMatch = useMutation({
    mutationFn: () => request("/api/v1/matches/{match_id}", "delete", { path: { match_id: match.id } }),
    onSuccess: async () => {
      queryClient.setQueryData<InfiniteData<MatchListPage, string | null>>(matchesKey, (current) => current === undefined
        ? current
        : {
            ...current,
            pages: current.pages.map((page) => ({
              ...page,
              items: page.items.filter((item) => item.id !== match.id),
            })),
          });
      queryClient.removeQueries({ queryKey: detailKey(match.id) });
      onDeleted(match.id);
      await queryClient.invalidateQueries({ queryKey: matchesKey });
    },
  });
  const reanalyze = useMutation({
    mutationFn: async () => {
      const savedMatch = await queryClient.ensureQueryData({
        queryKey: detailKey(match.id),
        queryFn: ({ signal }) => request("/api/v1/matches/{match_id}", "get", {
          path: { match_id: match.id }, signal, decode: decodeMatchDetail,
        }),
      });
      return request("/api/v1/matches/{match_id}/reanalyze", "post", {
        path: { match_id: match.id },
        body: { profile: match.processing.profile ?? "maximum", ballInputMode: savedMatch.latestJob?.ballInputMode ?? "original" },
        decode: decodeJob,
      });
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: matchesKey }),
        queryClient.invalidateQueries({ queryKey: detailKey(match.id) }),
      ]);
      navigate(`/matches/${match.id}/processing`);
    },
  });
  const proxy = detail.data?.assets.find((asset) => asset.kind === "proxy");
  const active = ["queued", "running", "paused", "failed", "cancelled"].includes(match.processing.state);
  const destination = active
    ? `/matches/${match.id}/processing`
    : match.latestReport === null
      ? `/matches/${match.id}/setup`
      : `/matches/${match.id}/analysis`;
  const displayTitle = match.title.trim().toLowerCase() === "untitled match"
    ? `${match.metadata.playerOne ?? "Player A"} vs ${match.metadata.playerTwo ?? "Player B"}`
    : match.title;

  return (
    <li className={`match-card${featured ? " match-card-featured" : ""}`} data-featured={featured ? "true" : undefined} aria-labelledby={`match-label-${match.id}`}>
      <span id={`match-label-${match.id}`} className="sr-only">{displayTitle} match</span>
      {featured ? (
        <div className="match-preview" data-ready={previewReady ? "true" : undefined}>
          {proxy !== undefined && !previewUnavailable ? (
            <video
              src={`/api/v1/matches/${encodeURIComponent(match.id)}/media/proxy`}
              muted
              aria-label={`${displayTitle} video preview`}
              preload="metadata"
              onLoadedMetadata={(event) => {
                if (Number.isFinite(event.currentTarget.duration) && event.currentTarget.duration > 0) event.currentTarget.currentTime = Math.min(0.2, event.currentTarget.duration / 2);
                else setPreviewUnavailable(true);
              }}
              onSeeked={() => setPreviewReady(true)}
              onError={() => setPreviewUnavailable(true)}
            />
          ) : null}
          {!previewReady ? (
            <div className="match-preview-fallback" role="img" aria-label={`${displayTitle} preview unavailable`}>
              <svg viewBox="0 0 80 100" width="64" height="80" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <path d="M5 5h70v90H5zM5 57h70M40 57v38M5 75h18v20M57 95V75h18M5 19h70" />
              </svg>
              <span>{detail.isPending ? "Loading preview…" : "Preview unavailable"}</span>
              <small>{detail.isPending ? "" : "Open the match to view its recording"}</small>
            </div>
          ) : null}
          <span>Latest match</span>
          <Link className="match-preview-open" to={destination} aria-label={`Continue with ${displayTitle}`}>
            <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor" aria-hidden="true"><path d="m8 5 11 7-11 7V5Z" /></svg>
          </Link>
        </div>
      ) : null}
      <div className="match-primary">
        <div className="match-card-state">
          <time dateTime={match.metadata.playedOn ?? match.updatedAt}>{match.metadata.playedOn ?? new Date(match.updatedAt).toLocaleDateString()}</time>
          <span className={`state state-${match.processing.state}`}>{processingLabel(match)}</span>
        </div>
        <h3>{displayTitle}</h3>
        <p className="match-player-names"><span className="player-a-mark">A</span>{match.metadata.playerOne ?? "Player A"}<span aria-hidden="true"> vs </span><span className="player-b-mark">B</span>{match.metadata.playerTwo ?? "Player B"}</p>
        {match.metadata.score ? <p className="match-score">{match.metadata.score}</p> : null}
      </div>
      <dl className="match-facts">
        <div><dt>Duration</dt><dd>{detail.isError ? "Duration unavailable" : durationLabel(proxy?.durationUs)}</dd></div>
        <div><dt>Tracking</dt><dd>{warningLabel(match.quality.availability)}</dd></div>
        <div><dt>Report</dt><dd>{match.latestReport === null ? "Not generated" : `Version ${match.latestReport.revision}`}</dd></div>
      </dl>
      {match.quality.warnings.length > 0 ? <ul className="warning-list" aria-label="Match warnings">{match.quality.warnings.map((warning) => <li key={warning}>{warningLabel(warning)}</li>)}</ul> : null}
      <div className="row-actions">
        <Link className="button-primary" to={destination}>{active ? "Resume" : "Open"}</Link>
        <details className="match-more">
          <summary>More options</summary>
          <div>
            <button type="button" className="button-secondary" disabled={reanalyze.isPending} onClick={() => reanalyze.mutate()}>Reanalyze</button>
            <button type="button" className="button-danger" disabled={deleteMatch.isPending} onClick={() => {
              if (window.confirm(`Delete ${match.title} and its local analysis?`)) deleteMatch.mutate();
            }}>Delete</button>
          </div>
        </details>
      </div>
      {deleteMatch.isError ? <p role="alert" className="status-error">Delete failed. Stop active processing, then try again.</p> : null}
      {reanalyze.isError ? <p role="alert" className="status-error">Reanalysis could not start. Check calibration and model readiness.</p> : null}
    </li>
  );
}
