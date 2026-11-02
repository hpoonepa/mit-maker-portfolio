import { type InfiniteData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { request } from "../../api/client";
import {
  decodeHealth,
  decodeMatchPage,
  decodeModels,
} from "../../api/decoders";
import type { MatchDetail, MatchListPage, MatchSummary, ModelAssetDetail } from "../../api/decoders";
import { AppShell } from "../../components/AppShell";
import { MatchCard } from "./MatchCard";
import { UploadDropzone } from "./UploadDropzone";

const queryKeys = {
  health: ["health"] as const,
  models: ["models"] as const,
  matches: ["matches"] as const,
  detail: (matchId: string) => ["matches", matchId] as const,
};


function modelSize(bytes: number | null): string {
  if (bytes === null) return "Size not published";
  return `${(bytes / (1024 * 1024)).toFixed(0)} MB`;
}


function ModelReadiness({ models }: { models: ModelAssetDetail[] }) {
  const queryClient = useQueryClient();
  const install = useMutation({
    mutationFn: async () => {
      const required = models.filter((model) => model.required && model.state !== "ready");
      const results = await Promise.allSettled(
        required.map((model) =>
          request("/api/v1/models/{name}/ensure", "post", {
            path: { name: model.name },
            decode: (value) => decodeModels([value])[0],
          }),
        ),
      );
      const failures = results
        .filter((result): result is PromiseRejectedResult => result.status === "rejected")
        .map((result) => result.reason);
      if (failures.length > 0) {
        throw new AggregateError(failures, `${failures.length} local model install failed`);
      }
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.models }),
        queryClient.invalidateQueries({ queryKey: queryKeys.health }),
      ]);
    },
  });
  const missing = models.filter((model) => model.required && model.state !== "ready");

  return (
    <section className="readiness-panel" aria-labelledby="models-heading">
      <h3 id="models-heading">Analysis models</h3>
      {models.length === 0 ? <p className="quiet">No model manifest entries reported.</p> : (
        <ul className="model-ledger">
          {models.map((model) => (
            <li key={model.name}>
              <span><strong>{model.filename}</strong><small>{model.sourceLabel}</small></span>
              <span>{modelSize(model.byteSize)} · {model.declaredLicense}</span>
              <span className={`state state-${model.state}`}>{model.state}</span>
            </li>
          ))}
        </ul>
      )}
      {missing.length > 0 ? (
        <button
          type="button"
          className="button-secondary"
          disabled={install.isPending}
          onClick={() => install.mutate()}
        >
          {install.isPending ? "Installing local models…" : "Install local models"}
        </button>
      ) : <p className="status-success">Analysis models ready</p>}
      {install.isError ? <p role="alert" className="status-error">Model install stopped. Check the local model source and try again.</p> : null}
    </section>
  );
}


export function MatchLibrary() {
  const queryClient = useQueryClient();
  const [announcement, setAnnouncement] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const matches = useInfiniteQuery({
    queryKey: queryKeys.matches,
    queryFn: ({ pageParam, signal }) => request("/api/v1/matches", "get", {
      query: { limit: 100, cursor: pageParam },
      signal,
      decode: decodeMatchPage,
    }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage, _pages, _lastPageParam, pageParams) => {
      const nextCursor = lastPage.nextCursor;
      return nextCursor === null || pageParams.includes(nextCursor) ? undefined : nextCursor;
    },
  });
  const health = useQuery({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => request("/api/v1/health", "get", { signal, decode: decodeHealth }),
  });
  const models = useQuery({
    queryKey: queryKeys.models,
    queryFn: ({ signal }) => request("/api/v1/models", "get", { signal, decode: decodeModels }),
  });

  const acceptUploaded = (match: MatchDetail): void => {
    queryClient.setQueryData<InfiniteData<MatchListPage, string | null>>(queryKeys.matches, (current) => {
      if (current === undefined) return current;
      const summary: MatchSummary = {
        id: match.id,
        title: match.title,
        metadata: match.metadata,
        updatedAt: match.updatedAt,
        version: match.version,
        preparationState: match.preparationState,
        processing: match.latestJob === null || match.latestJob === undefined
          ? { state: "not_started" }
          : {
              state: match.latestJob.state,
              jobId: match.latestJob.id,
              stage: match.latestJob.stage,
              profile: match.latestJob.profile,
              updatedAt: match.latestJob.updatedAt,
            },
        quality: match.quality,
        latestReport: match.latestReport ?? null,
      };
      const [firstPage, ...remainingPages] = current.pages;
      if (firstPage === undefined) return current;
      return {
        ...current,
        pages: [
          { ...firstPage, items: [summary, ...firstPage.items.filter((item) => item.id !== match.id)] },
          ...remainingPages.map((page) => ({
            ...page,
            items: page.items.filter((item) => item.id !== match.id),
          })),
        ],
      };
    });
    queryClient.setQueryData(queryKeys.detail(match.id), match);
  };

  const matchItems = matches.data?.pages.flatMap((page) => page.items) ?? [];
  const lastMatchPage = matches.data?.pages.at(-1);
  useEffect(() => {
    if (matches.data !== undefined && matchItems.length === 0) setImportOpen(true);
  }, [matchItems.length, matches.data]);
  const repeatedMatchCursor = lastMatchPage?.nextCursor !== null
    && lastMatchPage?.nextCursor !== undefined
    && matches.data?.pageParams.includes(lastMatchPage.nextCursor) === true;
  const systemReady = health.data?.status === "ready"
    && models.data?.every((model) => !model.required || model.state === "ready") === true;


  return (
    <AppShell active="library">
      <header className="library-header">
        <div className="library-intro">
          <h1>Matches</h1>
          <p>Review a match, or add a recording.</p>
        </div>
        <div className="library-toolbar" aria-label="Match list order">
          <span>{matchItems.length} {matchItems.length === 1 ? "match" : "matches"}</span>
          <span>Newest first</span>
        </div>
      </header>
      <p className="library-announcement" role="status" aria-live="polite">{announcement}</p>
      <div className="library-layout" data-empty={matchItems.length === 0 ? "true" : undefined}>
        <section className="ledger" aria-labelledby="ledger-heading">
          <h2 id="ledger-heading" className="sr-only">Match library</h2>
          {matches.isPending ? <div className="ledger-skeleton" aria-label="Loading matches">Loading matches…</div> : null}
          {matches.isError && matches.data === undefined ? (
            <div className="action-state" role="alert">
              <h3>Matches could not load</h3>
              <p>Check that SquashVision is running, then try again.</p>
              <button type="button" className="button-secondary" onClick={() => void matches.refetch()}>Retry loading matches</button>
            </div>
          ) : null}
          {matches.data !== undefined && matchItems.length === 0 ? (
            <div className="empty-state">
              <svg className="library-empty-court" viewBox="0 0 440 280" fill="none" aria-hidden="true">
                <path d="M119 32h202l78 212H41L119 32Z" fill="var(--surface-2)" stroke="var(--line-strong)" strokeWidth="1.5" />
                <path d="M119 32v88l-78 124M321 32v88l78 124M119 120h202" stroke="var(--line-strong)" strokeWidth="1.5" />
                <path d="M119 60h202M119 101h202M78 185h284M220 185v59M64 207h59v37M317 244v-37h59" stroke="var(--player-b)" strokeWidth="1.5" opacity=".65" />
                <path d="M119 60 41 160M321 60l78 100" stroke="var(--player-b)" strokeWidth="1.5" opacity=".65" />
                <circle cx="197" cy="205" r="5" fill="var(--player-a)" />
                <circle cx="264" cy="174" r="5" fill="var(--player-b)" />
              </svg>
              <h2>Start with a match video</h2>
              <p>Choose one MP4, MOV, M4V, or WebM recording, up to 3 hours and 20 GB.</p>
              <ol className="library-empty-steps">
                <li>Add your video</li>
                <li>Mark the court</li>
                <li>Review the rallies</li>
              </ol>
            </div>
          ) : null}
          {matchItems.length > 0 ? (
            <ul className="match-ledger">{matchItems.map((match, index) => (
              <MatchCard
                key={match.id}
                match={match}
                featured={index === 0}
                onDeleted={() => setAnnouncement("Match deleted")}
              />
            ))}</ul>
          ) : null}
          {repeatedMatchCursor ? (
            <div className="action-state" role="alert">
              <strong>Some matches could not load</strong>
              <p>The match list stopped responding correctly. Refresh the page to try again.</p>
            </div>
          ) : matches.isFetchNextPageError ? (
            <div className="action-state" role="alert">
              <strong>Additional matches unavailable</strong>
              <p>Your loaded matches are still available. Try again to load the rest.</p>
              <button type="button" className="button-secondary" disabled={matches.isFetchingNextPage} onClick={() => void matches.fetchNextPage()}>Retry loading matches</button>
            </div>
          ) : matches.hasNextPage ? (
            <button type="button" className="button-secondary" disabled={matches.isFetchingNextPage} onClick={() => void matches.fetchNextPage()}>
              {matches.isFetchingNextPage ? "Loading more matches…" : "Load more matches"}
            </button>
          ) : null}
        </section>
        <aside className="ingest-column">
          <details
            id="import"
            className="library-import"
            open={importOpen}
            onToggle={(event) => setImportOpen(event.currentTarget.open)}
          >
            <summary>Import a match video</summary>
            <UploadDropzone onUploaded={acceptUploaded} />
          </details>
          <details className="system-details" data-ready={systemReady}>
            <summary>
              <span>System status</span>
              <small>{health.isPending || models.isPending ? "Checking…" : systemReady ? "Ready" : "Needs attention"}</small>
            </summary>
            <div className="system-strip" aria-label="Local system readiness">
              <span>Video tools <strong>{health.data?.ffmpeg.status ?? (health.isError ? "unavailable" : "checking")}</strong></span>
              <span>Analysis worker <strong>{health.data?.worker.status ?? (health.isError ? "unavailable" : "checking")}</strong></span>
              <span>Storage <strong>checked at import</strong></span>
            </div>
            {models.isPending ? <div className="readiness-skeleton" aria-label="Loading model readiness">Checking model manifest…</div> : null}
            {models.isError ? <div role="alert" className="action-state">Model readiness unavailable. <button type="button" onClick={() => void models.refetch()}>Retry models</button></div> : null}
            {models.data ? <ModelReadiness models={models.data} /> : null}
          </details>
        </aside>
      </div>
    </AppShell>
  );
}
