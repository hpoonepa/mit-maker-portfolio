import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { request } from "../../api/client";
import { sourceFrameAt } from "./VideoOverlay";
import { decodePlaybackFrameMap, decodePlaybackTimeline, indexPlayback, playbackAt } from "./playback-model";
import type { PlaybackTimeline } from "./playback-model";

export function usePlaybackTimeline(matchId: string, reportRevision: number, currentTimeUs: number, calibrationRevision: number | null) {
  const proxyAnchor = Math.floor(Math.max(0, currentTimeUs) / 10_000_000) * 10_000_000;
  const mapStart = Math.max(0, proxyAnchor - 10_000_000);
  const mapEnd = proxyAnchor + 20_000_000;
  const frameMap = useQuery<ReturnType<typeof decodePlaybackFrameMap>>({
    queryKey: ["matches", matchId, "frame-map", mapStart, mapEnd],
    enabled: matchId !== "" && reportRevision > 0,
    staleTime: 60_000,
    placeholderData: (previous, query) => query?.queryKey[1] === matchId ? previous : undefined,
    queryFn: ({ signal }) => request("/api/v1/matches/{match_id}/media/frame-map", "get", { path: { match_id: matchId }, query: { startUs: mapStart, endUs: mapEnd }, signal, decode: decodePlaybackFrameMap }),
  });
  const sourceFrame = sourceFrameAt(frameMap.data?.items ?? [], currentTimeUs, false);
  const sourceTimeUs = sourceFrame?.sourceTimestampUs ?? null;
  const startUs = sourceTimeUs === null ? 0 : Math.max(0, Math.floor(sourceTimeUs / 60_000_000) * 60_000_000 - 30_000_000);
  const endUs = startUs + 120_000_000;
  const timeline = useQuery<PlaybackTimeline>({
    queryKey: ["matches", matchId, "tracking-timeline", reportRevision, calibrationRevision, startUs, endUs],
    enabled: sourceTimeUs !== null && reportRevision > 0,
    staleTime: 60_000,
    placeholderData: (previous, query) => query?.queryKey[1] === matchId && query.queryKey[3] === reportRevision && query.queryKey[4] === calibrationRevision ? previous : undefined,
    queryFn: async ({ signal }) => {
      const result = await request("/api/v1/matches/{match_id}/reports/{revision}/tracking-timeline", "get", { path: { match_id: matchId, revision: reportRevision }, query: { startUs, endUs, calibrationRevision: calibrationRevision ?? undefined }, signal, decode: decodePlaybackTimeline });
      if (result.reportRevision !== reportRevision) throw new Error("Playback data belongs to another report");
      return result;
    },
  });
  const data = sourceTimeUs !== null && timeline.data !== undefined && sourceTimeUs >= timeline.data.startUs && sourceTimeUs < timeline.data.endUs ? timeline.data : null;
  const index = useMemo(() => data === null ? null : indexPlayback(data), [data]);
  const snapshot = useMemo(() => index === null ? null : playbackAt(index, currentTimeUs), [index, currentTimeUs]);
  return {
    data, snapshot, error: frameMap.isError || timeline.isError,
    loading: !frameMap.isError && !timeline.isError && snapshot === null && (frameMap.isFetching || (sourceTimeUs !== null && timeline.isFetching)),
    retry: () => { void frameMap.refetch(); if (sourceTimeUs !== null) void timeline.refetch(); },
  };
}
