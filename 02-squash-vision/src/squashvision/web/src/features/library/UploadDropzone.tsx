import { useEffect, useRef, useState } from "react";

import { ApiError, uploadMatch } from "../../api/client";
import { decodeMatchDetail } from "../../api/decoders";
import type { MatchDetail } from "../../api/decoders";

const MAX_UPLOAD_BYTES = 20 * 1024 * 1024 * 1024;
const VIDEO_EXTENSIONS: Record<string, true> = { mp4: true, mov: true, m4v: true, webm: true };
const VIDEO_TYPES: Record<string, true> = {
  "video/mp4": true,
  "video/quicktime": true,
  "video/x-m4v": true,
  "video/webm": true,
};

type UploadState =
  | { kind: "idle" }
  | { kind: "uploading"; loaded: number; total: number | null }
  | { kind: "complete" }
  | { kind: "error"; message: string };

interface UploadDropzoneProps {
  onUploaded: (match: MatchDetail) => void;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function uploadFailure(error: unknown): string {
  if (!(error instanceof ApiError)) return "The local API could not receive this video. Try again.";
  if (error.code === "request_aborted") return "Upload cancelled. The local file was not changed.";
  if (error.code === "insufficient_disk") return "Free local disk space, then try again.";
  if (error.code === "upload_too_large") return "This video exceeds the 20 GB local upload limit.";
  if (error.code === "duration_exceeded") return "This video exceeds the 3-hour match limit. Choose a shorter recording.";
  if (error.code === "invalid_duration") return "The video duration could not be read. Re-export the file, then try again.";
  if (error.code === "no_video_stream") return "No video track was found. Choose a file that contains video.";
  if (error.code === "unsupported_container") return "Choose an MP4, MOV, M4V, or WebM video, or re-export the file.";
  if (error.code === "invalid_media") return "The video could not be decoded. Re-export it with a supported video codec.";
  if (error.code === "proxy_failed") return "The video timestamps could not be mapped. Re-export with standard timestamps.";
  if (error.status === 507) return "Free local disk space, then try again.";
  if (error.status === 413) return "This upload is larger than the local size limit.";
  if (error.status === 422) return "The upload was rejected. Review the file details and try again.";
  return error.message;
}

export function UploadDropzone({ onUploaded }: UploadDropzoneProps) {
  const [file, setFile] = useState<File | null>(null);
  const [state, setState] = useState<UploadState>({ kind: "idle" });
  const [dragging, setDragging] = useState(false);
  const [focused, setFocused] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
      controller.current = null;
    };
  }, []);

  const selectFile = (candidate: File | null): void => {
    if (controller.current !== null || state.kind === "uploading") return;
    setState({ kind: "idle" });
    if (candidate === null) {
      setFile(null);
      return;
    }
    const extension = candidate.name.split(".").pop()?.toLowerCase() ?? "";
    if (!(extension in VIDEO_EXTENSIONS) || (candidate.type !== "" && !(candidate.type in VIDEO_TYPES))) {
      setFile(null);
      setState({ kind: "error", message: "Choose an MP4, MOV, M4V, or WebM video." });
      return;
    }
    if (candidate.size > MAX_UPLOAD_BYTES) {
      setFile(null);
      setState({ kind: "error", message: "This video exceeds the 20 GB local upload limit." });
      return;
    }
    setFile(candidate);
  };

  const submit = (form: HTMLFormElement): void => {
    if (file === null || controller.current !== null || state.kind === "uploading") return;
    const values = new FormData(form);
    const nextController = new AbortController();
    controller.current = nextController;
    setState({ kind: "uploading", loaded: 0, total: file.size });
    void uploadMatch(file, {
      metadata: {
        title: String(values.get("title") ?? "").trim() || null,
        playerOne: String(values.get("playerOne") ?? "").trim() || null,
        playerTwo: String(values.get("playerTwo") ?? "").trim() || null,
        playedOn: String(values.get("playedOn") ?? "").trim() || null,
        score: String(values.get("score") ?? "").trim() || null,
      },
      signal: nextController.signal,
      decode: decodeMatchDetail,
      onProgress: (loaded, total) => {
        if (mounted.current) setState({ kind: "uploading", loaded, total });
      },
    })
      .then((match) => {
        if (!mounted.current) return;
        setState({ kind: "complete" });
        setFile(null);
        onUploaded(match);
      })
      .catch((error: unknown) => {
        if (mounted.current) setState({ kind: "error", message: uploadFailure(error) });
      })
      .finally(() => {
        if (mounted.current) controller.current = null;
      });
  };

  const progress = state.kind === "uploading" && state.total !== null && state.total > 0
    ? Math.min(100, Math.round((state.loaded / state.total) * 100))
    : null;
  const preparing = state.kind === "uploading" && progress === 100;

  return (
    <section className="ingest-bay" aria-labelledby="ingest-heading">
      <h2 id="ingest-heading" className="sr-only">Choose a recording</h2>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit(event.currentTarget);
        }}
      >
        <label
          className="dropzone"
          data-dragging={dragging}
          data-focused={focused}
          data-uploading={state.kind === "uploading"}
          aria-disabled={state.kind === "uploading"}
          onDragEnter={(event) => {
            event.preventDefault();
            if (controller.current === null) setDragging(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            if (controller.current !== null || state.kind === "uploading") return;
            if (event.dataTransfer.files.length !== 1) {
              setState({ kind: "error", message: "Choose exactly one video at a time." });
              return;
            }
            selectFile(event.dataTransfer.files[0] ?? null);
          }}
        >
          <input
            type="file"
            accept=".mp4,.mov,.m4v,.webm,video/mp4,video/quicktime,video/webm"
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            aria-label="Choose one match video"
            disabled={state.kind === "uploading"}
            onChange={(event) => {
              selectFile(event.currentTarget.files?.[0] ?? null);
              event.currentTarget.value = "";
            }}
          />
          <svg className="dropzone-icon" viewBox="0 0 32 32" width="32" height="32" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            <path d="M16 22V5m-6 6 6-6 6 6M5 20v6a2 2 0 0 0 2 2h18a2 2 0 0 0 2-2v-6" />
          </svg>
          <span className="dropzone-title">
            {preparing ? "Preparing your match" : state.kind === "uploading" ? "Importing your match" : file === null ? "Choose a match video" : "Choose a different video"}
          </span>
          <span>
            {preparing ? "Making the recording ready for playback. Longer matches take more time."
              : state.kind === "uploading"
              ? "Cancel this upload before choosing another video."
              : "Drop a full match here or browse. MP4, MOV, M4V, or WebM, up to 3 hours and 20 GB."}
          </span>
        </label>

        {file !== null && state.kind !== "complete" ? (
          <div className="file-selection" aria-live="polite">
            <span className="file-selection-mark" aria-hidden="true">▶</span>
            <span><strong>{file.name}</strong><small>{formatBytes(file.size)} · {state.kind === "uploading" ? "importing" : "ready to import"}</small></span>
          </div>
        ) : null}
        {file !== null && state.kind !== "complete" ? (
          <div className="metadata-fields">
            <label>Match title<input name="title" aria-label="Match title" /></label>
            <label>Player A<input name="playerOne" aria-label="Player A" /></label>
            <label>Player B<input name="playerTwo" aria-label="Player B" /></label>
            <label>Date<input name="playedOn" aria-label="Match date" type="date" /></label>
            <label>Score<input name="score" aria-label="Match score" placeholder="3–1" /></label>
          </div>
        ) : null}

        {state.kind === "uploading" ? (
          <div className="upload-status" aria-live="polite">
            <progress
              value={progress ?? undefined}
              max={100}
              aria-label="Video upload progress"
              aria-valuenow={progress ?? undefined}
            />
            <span>
              {formatBytes(state.loaded)}{state.total === null ? " uploaded" : ` of ${formatBytes(state.total)} uploaded`}
            </span>
            <button type="button" className="button-secondary" onClick={() => controller.current?.abort()}>
              Cancel upload
            </button>
          </div>
        ) : (
          <button type="submit" className="button-primary" disabled={file === null}>
            {state.kind === "error" && file !== null ? "Retry upload" : "Upload match"}
          </button>
        )}
        {state.kind === "error" ? <p role="alert" className="status-error">{state.message}</p> : null}
        {state.kind === "complete" ? <p role="status" className="status-success">Upload complete</p> : null}
        <p className="quiet upload-privacy">Your video stays on this device.</p>
      </form>
    </section>
  );
}
