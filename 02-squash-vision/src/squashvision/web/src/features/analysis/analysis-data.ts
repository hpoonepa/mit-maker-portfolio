import { request } from "../../api/client";
import {
  decodeBallObservationPage,
  decodePlayerObservationPage,
  decodeReportList,
  decodeReviewItemPage,
  decodeShotPage,
  decodeTimelinePage,
} from "../../api/decoders";
import type { BallObservationPage, PlayerObservationPage, ReportListPage, ReviewItemPage, ShotDetail, ShotPage, TimelinePage } from "../../api/decoders";
import type { components } from "../../api/types.generated";
import type { ReviewItem } from "../review/review-model";

export class IncompletePageError<T> extends Error {
  constructor(message: string, readonly items: T[]) {
    super(message);
    this.name = "IncompletePageError";
  }
}

type ApiReviewItem = components["schemas"]["ReviewItemDetail"];
type BallObservation = components["schemas"]["BallObservationDetail"];
type PlayerObservation = components["schemas"]["PlayerObservationDetail"];
type ReportSummary = components["schemas"]["ReportSummary"];
type TimelineItem = components["schemas"]["TimelineItem"];

const PAGE_LIMIT = 500;
const MAX_CURSOR_PAGES = 8;

export const analysisKeys = {
  match: (matchId: string) => ["matches", matchId] as const,
  reports: (matchId: string) => ["matches", matchId, "reports"] as const,
  latestReport: (matchId: string) => ["matches", matchId, "reports", "latest"] as const,
  report: (matchId: string, revision: number) => ["matches", matchId, "reports", revision] as const,
  timeline: (matchId: string, reportRevision: number, jobId: string, startUs: number, endUs: number, kinds: string) => ["matches", matchId, "analysis", "timeline", reportRevision, jobId, startUs, endUs, kinds] as const,
  observations: (matchId: string, reportRevision: number, jobId: string, kind: "players" | "ball", startUs: number, endUs: number) => ["matches", matchId, "analysis", "observations", reportRevision, jobId, startUs, endUs, kind] as const,
  review: (matchId: string, reportRevision: number) => ["matches", matchId, "analysis", "review", reportRevision] as const,
  conflicts: (matchId: string, reportRevision?: number) => reportRevision === undefined ? ["matches", matchId, "correction-conflicts"] as const : ["matches", matchId, "correction-conflicts", reportRevision] as const,
};

export async function allReportPages(matchId: string, signal: AbortSignal): Promise<ReportListPage> {
  const items: ReportSummary[] = [];
  const seen = new Set<string>();
  let cursor: string | null = null;
  while (!signal.aborted) {
    let page: ReportListPage;
    try {
      page = await request("/api/v1/matches/{match_id}/reports", "get", {
        path: { match_id: matchId }, query: { limit: 50, ...(cursor === null ? {} : { cursor }) }, signal, decode: decodeReportList,
      });
    } catch (error) {
      if (signal.aborted) throw error;
      throw new IncompletePageError("report history paging stopped before completion", [...items]);
    }
    items.push(...page.items);
    if (page.nextCursor === null) return { items, nextCursor: null };
    if (seen.has(page.nextCursor)) throw new IncompletePageError("report history cursor repeated before completion", [...items]);
    seen.add(page.nextCursor);
    cursor = page.nextCursor;
  }
  throw new DOMException("report history request was aborted", "AbortError");
}

export async function allTimelinePages(matchId: string, reportRevision: number, startUs: number, endUs: number, kinds: string, signal: AbortSignal): Promise<TimelinePage> {
  const items: TimelineItem[] = [];
  let cursor: string | null = null;
  let predictionRevision = 0;
  const seen = new Set<string>();
  for (let pageIndex = 0; pageIndex < MAX_CURSOR_PAGES; pageIndex += 1) {
    const page: TimelinePage = await request("/api/v1/matches/{match_id}/timeline", "get", {
      path: { match_id: matchId }, query: { startUs, endUs, revision: reportRevision, limit: PAGE_LIMIT, kinds, ...(cursor === null ? {} : { cursor }) }, signal, decode: decodeTimelinePage,
    });
    predictionRevision = page.predictionRevision;
    items.push(...page.items);
    if (page.nextCursor === null || seen.has(page.nextCursor)) return { items, nextCursor: page.nextCursor, predictionRevision };
    seen.add(page.nextCursor);
    cursor = page.nextCursor;
  }
  return { items, nextCursor: cursor, predictionRevision };
}

export async function allPlayerPages(matchId: string, reportRevision: number, startUs: number, endUs: number, signal: AbortSignal): Promise<PlayerObservation[]> {
  const items: PlayerObservation[] = [];
  let cursor: string | null = null;
  const seen = new Set<string>();
  for (let pageIndex = 0; pageIndex < MAX_CURSOR_PAGES; pageIndex += 1) {
    const page: PlayerObservationPage = await request("/api/v1/matches/{match_id}/observations/players", "get", {
      path: { match_id: matchId }, query: { startUs, endUs, revision: reportRevision, limit: PAGE_LIMIT, ...(cursor === null ? {} : { cursor }) }, signal, decode: decodePlayerObservationPage,
    });
    items.push(...page.items);
    if (page.nextCursor === null || seen.has(page.nextCursor)) return items;
    seen.add(page.nextCursor);
    cursor = page.nextCursor;
  }
  return items;
}

export async function allBallPages(matchId: string, reportRevision: number, startUs: number, endUs: number, signal: AbortSignal): Promise<BallObservation[]> {
  const items: BallObservation[] = [];
  let cursor: string | null = null;
  const seen = new Set<string>();
  for (let pageIndex = 0; pageIndex < MAX_CURSOR_PAGES; pageIndex += 1) {
    const page: BallObservationPage = await request("/api/v1/matches/{match_id}/observations/ball", "get", {
      path: { match_id: matchId }, query: { startUs, endUs, revision: reportRevision, limit: PAGE_LIMIT, ...(cursor === null ? {} : { cursor }) }, signal, decode: decodeBallObservationPage,
    });
    items.push(...page.items);
    if (page.nextCursor === null || seen.has(page.nextCursor)) return items;
    seen.add(page.nextCursor);
    cursor = page.nextCursor;
  }
  return items;
}

function normalizedReviewItem(item: ApiReviewItem): ReviewItem {
  const provenance = item.provenance === "observed" || item.provenance === "reconstructed" || item.provenance === "ambiguous" ? item.provenance : "unavailable";
  return { ...item, endUs: item.endUs ?? null, confidence: item.confidence ?? null, summary: item.summary ?? {}, evidenceStartFrameIndex: item.evidenceStartFrameIndex ?? null, evidenceEndFrameIndex: item.evidenceEndFrameIndex ?? null, provenance };
}

export async function allReviewPages(matchId: string, reportRevision: number, signal: AbortSignal): Promise<ReviewItem[]> {
  const items: ReviewItem[] = [];
  const seen = new Set<string>();
  let cursor: string | null = null;
  while (!signal.aborted) {
    let page: ReviewItemPage;
    try {
      page = await request("/api/v1/matches/{match_id}/review-items", "get", {
        path: { match_id: matchId }, query: { revision: reportRevision, limit: PAGE_LIMIT, ...(cursor === null ? {} : { cursor }) }, signal, decode: decodeReviewItemPage,
      });
    } catch (error) {
      if (signal.aborted) throw error;
      throw new IncompletePageError("review queue paging stopped before completion", [...items]);
    }
    items.push(...page.items.map(normalizedReviewItem));
    if (page.nextCursor === null) return items;
    if (seen.has(page.nextCursor)) throw new IncompletePageError("review item cursor repeated before the complete queue was loaded", [...items]);
    seen.add(page.nextCursor);
    cursor = page.nextCursor;
  }
  throw new DOMException("review item request was aborted", "AbortError");
}

export function revisionFromSearch(value: string | null): number | null {
  if (value === null || value.trim() === "") return null;
  const revision = Number(value);
  return Number.isSafeInteger(revision) && revision > 0 ? revision : null;
}

export async function allShotPages(
  matchId: string,
  reportRevision: number,
  predictionRevision: number,
  endUs: number,
  signal: AbortSignal,
): Promise<ShotDetail[]> {
  const items: ShotDetail[] = [];
  const seen = new Set<string>();
  let cursor: string | null = null;
  while (!signal.aborted) {
    let page: ShotPage;
    try {
      page = await request("/api/v1/matches/{match_id}/shots", "get", {
        path: { match_id: matchId },
        query: { startUs: 0, endUs: Math.max(1, endUs), reportRevision, limit: 500, ...(cursor === null ? {} : { cursor }) },
        signal,
        decode: decodeShotPage,
      });
    } catch (error) {
      if (signal.aborted) throw error;
      throw new IncompletePageError("shot evidence paging stopped before completion", [...items]);
    }
    if (page.predictionRevision !== predictionRevision) {
      throw new IncompletePageError(`shot page prediction revision ${page.predictionRevision} did not match report prediction revision ${predictionRevision}`, [...items]);
    }
    items.push(...page.items);
    if (page.nextCursor === null) return items;
    if (seen.has(page.nextCursor)) {
      throw new IncompletePageError("shot evidence cursor repeated before completion", [...items]);
    }
    seen.add(page.nextCursor);
    cursor = page.nextCursor;
  }
  throw new DOMException("shot evidence request was aborted", "AbortError");
}
