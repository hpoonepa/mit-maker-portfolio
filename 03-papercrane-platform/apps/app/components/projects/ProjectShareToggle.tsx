"use client";

import { useState } from "react";
import { Check, Copy, ExternalLink, Loader2 } from "lucide-react";
import { trpc } from "@/lib/trpc/client";

/**
 * ProjectShareToggle: toggle a project to "publicly viewable" so anyone with
 * the link can read its targets/designs without authentication. Off by default.
 *
 * The component flips between two states:
 *   - private: shows a "Make public" toggle, no URL
 *   - public:  shows a mono URL `papercrane.bio/p/<publicId>` with a
 *              copy-to-clipboard button + a "Make private" toggle
 *
 * Security note (live mode): the public flag is the source of truth on the
 * server. Toggling off must invalidate any cached public reads: never trust
 * the client-side state for access control.
 */
export interface ProjectShareToggleProps {
  projectId: string;
  /** Server-authoritative state from `projects.get`. */
  isPublic?: boolean;
  /** Stable opaque public id; only meaningful when `isPublic` is true. */
  publicId?: string | null;
}

const PUBLIC_BASE = "papercrane.bio/p";

export function ProjectShareToggle({
  projectId,
  isPublic: initialIsPublic = false,
  publicId: initialPublicId = null,
}: ProjectShareToggleProps) {
  const [copied, setCopied] = useState(false);
  const [isPublic, setIsPublic] = useState(initialIsPublic);
  const [publicId, setPublicId] = useState(initialPublicId);
  const utils = trpc.useUtils();
  const share = trpc.projects.share.useMutation({
    onSuccess: (result) => {
      setIsPublic(result.isPublic);
      setPublicId(result.publicId);
      setCopied(false);
      void utils.projects.get.invalidate({ id: projectId });
      void utils.projects.list.invalidate();
    },
  });
  const displayUrl = publicId ? `${PUBLIC_BASE}/${publicId}` : null;
  const absoluteUrl = displayUrl ? `https://${displayUrl}` : null;

  async function copyUrl() {
    if (!absoluteUrl) return;
    try {
      await navigator.clipboard.writeText(absoluteUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard unavailable (insecure context, denied permission). Silent.
    }
  }

  return (
    <section
      data-testid="e2e-project-share-toggle"
      aria-labelledby="project-sharing-heading"
      className="py-4"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            <h3
              id="project-sharing-heading"
              className="font-sans text-[14px] font-medium text-ink"
            >
              Sharing
            </h3>
            <span className="font-sans text-[12px] text-graphite-soft">
              {isPublic ? "Public link active" : "Private"}
            </span>
          </div>
          <p className="mt-1 max-w-2xl font-sans text-[12px] leading-5 text-graphite">
            {isPublic
              ? "Anyone with the link can view the project summary. Sequences, structures, logs, and settings remain private."
              : "Only workspace members can view this project."}
          </p>
        </div>
        <button
          type="button"
          aria-pressed={isPublic}
          disabled={share.isPending}
          onClick={() => share.mutate({ id: projectId, isPublic: !isPublic })}
          className={`inline-flex min-h-9 shrink-0 items-center justify-center gap-2 rounded-md px-3 py-2 font-sans text-[12px] font-medium transition-colors disabled:cursor-wait disabled:opacity-60 ${
            isPublic
              ? "border border-lattice-strong bg-paper text-ink hover:bg-paper-fold"
              : "bg-ink text-paper hover:bg-ink-soft"
          }`}
        >
          {share.isPending && (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          )}
          {isPublic ? "Disable link" : "Create public link"}
        </button>
      </div>

      {isPublic && displayUrl && absoluteUrl ? (
        <div className="mt-3 flex flex-col gap-2 pt-3 sm:flex-row sm:items-center">
          <div className="flex min-w-0 flex-1 items-center rounded-md px-3 py-2">
            <code className="min-w-0 flex-1 truncate px-2 font-mono text-[12px] text-ink">
              {displayUrl}
            </code>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={copyUrl}
              data-testid="e2e-project-share-copy"
              aria-label="Copy public URL"
              className="inline-flex min-h-9 flex-1 items-center justify-center gap-1.5 rounded-md px-3 font-sans text-[12px] text-graphite transition-colors hover:bg-paper-fold hover:text-ink sm:flex-none"
            >
              {copied ? (
                <Check className="h-3.5 w-3.5" aria-hidden />
              ) : (
                <Copy className="h-3.5 w-3.5" aria-hidden />
              )}
              {copied ? "Copied" : "Copy"}
            </button>
            <a
              href={absoluteUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-grid h-9 w-9 place-items-center rounded-md text-graphite transition-colors hover:bg-paper-fold hover:text-ink"
              aria-label="Open public report"
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            </a>
          </div>
        </div>
      ) : null}

      {share.error && (
        <p role="alert" className="mt-3 font-sans text-[12px] text-crane-deep">
          Couldn&apos;t update sharing. Please try again.
        </p>
      )}
    </section>
  );
}

export default ProjectShareToggle;
