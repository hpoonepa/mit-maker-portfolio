import { useMutation } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { ApiError, request } from "../../api/client";
import { decodeExportDetail } from "../../api/decoders";
import type { ExportDetail, MatchReport } from "../../api/decoders";

type ExportFormat = "html" | "json" | "csv";

const FORMAT_OPTIONS: ReadonlyArray<{ id: ExportFormat; label: string; detail: string }> = [
  { id: "html", label: "Offline report", detail: "Opens in a browser" },
  { id: "json", label: "Analysis data", detail: "JSON" },
  { id: "csv", label: "Evidence tables", detail: "CSV" },
];

interface ExportControlsProps {
  matchId: string;
  report: MatchReport;
}

function completedDownload(matchId: string, detail: ExportDetail): string {
  return `/api/v1/matches/${encodeURIComponent(matchId)}/exports/${encodeURIComponent(detail.id)}/download`;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "The local export could not be built. Review the selection and retry.";
}

export function ExportControls({ matchId, report }: ExportControlsProps) {
  const [formats, setFormats] = useState<ExportFormat[]>(["html", "json", "csv"]);
  const [includeEvidence, setIncludeEvidence] = useState(false);
  const [includeOriginal, setIncludeOriginal] = useState(false);
  const evidenceIds = useMemo(() => {
    const unique = new Set<string>();
    for (const name of Object.keys(report.sections).sort()) {
      for (const evidenceId of report.sections[name]?.evidenceIds ?? []) {
        if (unique.size < 100) unique.add(evidenceId);
      }
    }
    return [...unique];
  }, [report.sections]);

  const createExport = useMutation({
    mutationFn: () => {
      if (formats.length === 0) throw new Error("Choose at least one export format.");
      if (includeEvidence && evidenceIds.length === 0) {
        throw new Error("This report revision has no published evidence clips to include.");
      }
      return request("/api/v1/matches/{match_id}/exports", "post", {
        path: { match_id: matchId },
        body: {
          revision: report.revision,
          selection: {
            formats,
            evidenceIds: includeEvidence ? evidenceIds : [],
            evidenceDurationSeconds: 6,
            includeOriginal,
          },
        },
        decode: decodeExportDetail,
      });
    },
  });

  const toggleFormat = (format: ExportFormat): void => {
    createExport.reset();
    setFormats((current) => current.includes(format)
      ? current.filter((item) => item !== format)
      : FORMAT_OPTIONS.filter((item) => current.includes(item.id) || item.id === format).map((item) => item.id));
  };

  return (
    <section className="export-console" aria-labelledby="export-heading">
      <div className="export-console-heading">
        <div>
          <p className="kicker">Report revision {report.revision}</p>
          <h2 id="export-heading">Export report</h2>
        </div>
        <p className="export-privacy">Download the report with optional video clips.</p>
      </div>

      <div className="export-console-grid">
        <details className="export-options">
          <summary>
            <span><strong>Export options</strong><small>{formats.length} {formats.length === 1 ? "format" : "formats"} selected · media {includeEvidence || includeOriginal ? "included" : "off"}</small></span>
          </summary>
          <div className="export-options-grid">
            <fieldset className="export-formats">
              <legend>File formats</legend>
              {FORMAT_OPTIONS.map((option) => (
                <label key={option.id}>
                  <input
                    type="checkbox"
                    checked={formats.includes(option.id)}
                    onChange={() => toggleFormat(option.id)}
                  />
                  <span><strong>{option.label}</strong><small>{option.detail}</small></span>
                </label>
              ))}
            </fieldset>

            <fieldset className="export-extras">
              <legend>Media options</legend>
              <label>
                <input
                  type="checkbox"
                  aria-label="Include evidence clips"
                  checked={includeEvidence}
                  disabled={evidenceIds.length === 0}
                  onChange={(event) => { createExport.reset(); setIncludeEvidence(event.currentTarget.checked); }}
                />
                <span><strong>Include evidence clips</strong><small>{evidenceIds.length === 0 ? "No clips are available in this revision" : `${evidenceIds.length} ${evidenceIds.length === 1 ? "clip" : "clips"} · six seconds each`}</small></span>
              </label>
              <label aria-describedby="original-size-warning">
                <input
                  type="checkbox"
                  aria-label="Include original video"
                  checked={includeOriginal}
                  onChange={(event) => { createExport.reset(); setIncludeOriginal(event.currentTarget.checked); }}
                />
                <span><strong>Include original video</strong><small id="original-size-warning">Including the original video increases the download size.</small></span>
              </label>
            </fieldset>
          </div>
        </details>
        <div className="export-action">
          <button
            type="button"
            disabled={createExport.isPending || formats.length === 0}
            onClick={() => createExport.mutate()}
          >
            {createExport.isPending ? "Building local export…" : "Build local export"}
          </button>
        </div>
      </div>

      {formats.length === 0 ? <div className="status-neutral" role="status">Choose at least one export format.</div> : null}
      {createExport.isError ? <div className="status-error" role="alert"><strong>Export not completed</strong><p>{errorMessage(createExport.error)}</p><button type="button" onClick={() => createExport.mutate()}>Retry export</button></div> : null}
      {createExport.data?.state === "completed" ? (
        <div className="export-complete" role="status">
          <div><p className="kicker">Export ready</p><strong>{(createExport.data.byteSize / 1024).toFixed(1)} KiB</strong><span className="technical-id">SHA-256 {createExport.data.sha256.slice(0, 16)}…</span></div>
          <a href={completedDownload(matchId, createExport.data)} download>Download completed export</a>
        </div>
      ) : null}
    </section>
  );
}
