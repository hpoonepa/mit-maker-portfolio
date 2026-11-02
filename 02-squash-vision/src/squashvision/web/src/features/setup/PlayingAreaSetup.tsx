import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, request } from "../../api/client";
import { clientPointToImage, videoContentRect } from "./CourtOverlayEditor";
import { decodePlayingArea, validPlayingArea } from "./player-roi";
import type { PlayingAreaPoint } from "./player-roi";

interface Props {
  matchId: string;
  modelsReady: boolean;
  starting: boolean;
  startError: string | null;
  profilePicker?: ReactNode;
  onReadinessChange: (ready: boolean) => void;
  onStart: () => void;
}

export function PlayingAreaSetup({ matchId, modelsReady, starting, startError, profilePicker, onReadinessChange, onStart }: Props) {
  const queryClient = useQueryClient();
  const videoRef = useRef<HTMLVideoElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const helpId = useId();
  const [draft, setDraft] = useState<PlayingAreaPoint[] | null>(null);
  const [editing, setEditing] = useState(false);
  const [cursor, setCursor] = useState<PlayingAreaPoint>({ x: 0, y: 0 });
  const [videoReady, setVideoReady] = useState(false);
  const [videoError, setVideoError] = useState(false);
  const queryKey = ["matches", matchId, "playing-area"] as const;
  const area = useQuery({ queryKey, queryFn: ({ signal }) => request("/api/v1/matches/{match_id}/player-roi", "get", { path: { match_id: matchId }, signal, decode: decodePlayingArea }) });
  const points = draft ?? area.data?.points ?? [];
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(area.data?.points ?? []);
  const ready = area.isSuccess && !area.isFetching && area.data.points !== null && !dirty;
  useEffect(() => { onReadinessChange(ready); }, [onReadinessChange, ready]);
  useEffect(() => {
    if (area.data === undefined) return;
    setCursor({ x: Math.round(area.data.frameSize.width / 2), y: Math.round(area.data.frameSize.height / 2) });
    setDraft(null);
    setEditing(false);
  }, [area.data?.sourceSha256, area.data?.frameSize.width, area.data?.frameSize.height]);
  const save = useMutation({
    mutationFn: () => {
      if (area.data === undefined || !validPlayingArea(points)) throw new Error("Choose at least three corners around the playing area.");
      return request("/api/v1/matches/{match_id}/player-roi", "put", { path: { match_id: matchId }, body: { expectedRevision: area.data.revision, sourceSha256: area.data.sourceSha256, frameSize: area.data.frameSize, points }, decode: decodePlayingArea });
    },
    onSuccess: (saved) => { queryClient.setQueryData(queryKey, saved); setDraft(null); setEditing(false); },
  });
  const updateDraft = (next: PlayingAreaPoint[]): void => { save.reset(); setDraft(next); };
  const addPoint = (point: PlayingAreaPoint): void => { if (points.length < 16) updateDraft([...points, point]); };

  return (
    <section className="playing-area-setup" aria-labelledby={`${helpId}-title`}>
      <header><h2 id={`${helpId}-title`}>Playing area</h2><p>Outline the court floor to keep spectators out of player tracking.</p></header>
      {area.isPending ? <p role="status">Loading playing area…</p> : area.isError ? <div className="status-error" role="alert"><p>The playing area could not be loaded.</p><button type="button" onClick={() => void area.refetch()}>Retry playing area</button></div> : (
        <>
          <div className="video-stage playing-area-stage">
            <video ref={videoRef} src={`/api/v1/matches/${encodeURIComponent(matchId)}/media/proxy`} controls={!editing} preload="metadata" playsInline aria-label="Playing area video" onLoadedMetadata={() => { setVideoReady(true); setVideoError(false); }} onError={() => { setVideoReady(false); setVideoError(true); }} />
            <svg ref={svgRef} className="court-overlay playing-area-overlay" viewBox={`0 0 ${area.data.frameSize.width} ${area.data.frameSize.height}`} preserveAspectRatio="xMidYMid meet" style={{ pointerEvents: editing ? "auto" : "none" }} role="group" aria-label="Draw playing area" aria-describedby={helpId} tabIndex={editing ? 0 : -1}
              onClick={(event) => {
                if (!editing || save.isPending || svgRef.current === null) return;
                const bounds = videoContentRect(svgRef.current.getBoundingClientRect(), area.data.frameSize);
                if (event.clientX < bounds.left || event.clientY < bounds.top || event.clientX > bounds.left + bounds.width || event.clientY > bounds.top + bounds.height) return;
                const raw = clientPointToImage({ x: event.clientX, y: event.clientY }, bounds, area.data.frameSize);
                const point = { x: Math.min(area.data.frameSize.width - 1, raw.x), y: Math.min(area.data.frameSize.height - 1, raw.y) };
                addPoint(point);
                setCursor(point);
              }}
              onKeyDown={(event) => {
                if (!editing || save.isPending) return;
                if (event.key === "Enter" || event.key === " ") { event.preventDefault(); addPoint(cursor); return; }
                if (event.key === "Backspace") { event.preventDefault(); updateDraft(points.slice(0, -1)); return; }
                const amount = event.shiftKey ? 50 : 10;
                const deltas: Record<string, PlayingAreaPoint> = { ArrowLeft: { x: -amount, y: 0 }, ArrowRight: { x: amount, y: 0 }, ArrowUp: { x: 0, y: -amount }, ArrowDown: { x: 0, y: amount } };
                const delta = deltas[event.key];
                if (delta === undefined) return;
                event.preventDefault();
                setCursor({ x: Math.max(0, Math.min(area.data.frameSize.width - 1, cursor.x + delta.x)), y: Math.max(0, Math.min(area.data.frameSize.height - 1, cursor.y + delta.y)) });
              }}>
              <polygon className="court-lines manual-lines" points={points.map((point) => `${point.x},${point.y}`).join(" ")} data-testid="playing-area-polygon" />
              {points.map((point, index) => <g key={index} aria-hidden="true"><circle className="calibration-handle" cx={point.x} cy={point.y} r={10} /><text className="calibration-label" x={point.x + 14} y={Math.max(24, point.y - 14)}>{index + 1}</text></g>)}
              {editing ? <circle className="playing-area-cursor" cx={cursor.x} cy={cursor.y} r={16} fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true" /> : null}
            </svg>
          </div>
          {videoError ? <p className="status-error" role="alert">The video could not be loaded. Reload the page to choose a playing area.</p> : null}
          <p id={helpId}>{editing ? "Click 3–16 corners around the floor in order. Use arrow keys to move the cursor and Enter to add a point; Backspace removes the last point." : "Pause on a clear court view, then choose Draw playing area."}</p>
          <div className="playing-area-actions">
            <button type="button" className="button-secondary" disabled={!videoReady || save.isPending} onClick={() => { if (!editing) videoRef.current?.pause(); setEditing(!editing); }}>{editing ? "Choose video frame" : "Draw playing area"}</button>
            <button type="button" className="button-secondary" disabled={points.length === 0 || save.isPending} onClick={() => updateDraft(points.slice(0, -1))}>Undo point</button>
            <button type="button" className="button-secondary" disabled={points.length === 0 || save.isPending} onClick={() => updateDraft([])}>Reset area</button>
            <button type="button" className="button-primary" disabled={!dirty || !validPlayingArea(points) || save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Saving area…" : "Save playing area"}</button>
          </div>
          <p role="status">{ready ? "Playing area saved" : dirty ? `${points.length} points · unsaved changes` : "No playing area saved"}</p>
          {points.length >= 3 && !validPlayingArea(points) ? <p className="status-neutral">Place corners around the edge in order, without crossed edges or inward bends.</p> : null}
          {save.isError ? <div className="status-error" role="alert"><p>{save.error instanceof ApiError && save.error.code === "active_analysis_exists" ? "Finish or cancel the current analysis before changing its playing area." : save.error instanceof ApiError && save.error.status === 409 ? "The source video or saved area changed. Reload the saved area before trying again." : "The area could not be saved. Check the corners and try again."}</p>{save.error instanceof ApiError && save.error.status === 409 && save.error.code !== "active_analysis_exists" ? <button type="button" onClick={() => { setDraft(null); save.reset(); void area.refetch(); }}>Reload saved area</button> : null}</div> : null}
        </>
      )}
      {profilePicker}
      <div className="playing-area-start">
        <p>Tracks player limbs and the ball across the recording. Use one fixed full-court camera for the whole match. Court distances require a separate calibration.</p>
        {!modelsReady ? <p>Install the required models before starting tracking.</p> : null}
        <button type="button" className="button-primary" disabled={!ready || !modelsReady || starting || save.isPending} onClick={onStart}>{starting ? "Starting tracking…" : "Start tracking"}</button>
        {startError === null ? null : <p className="status-error" role="alert">{startError}</p>}
      </div>
    </section>
  );
}
