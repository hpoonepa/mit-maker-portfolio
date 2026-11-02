"use client";

import { X } from "lucide-react";
import Image from "next/image";
import { useEffect, useMemo, useState } from "react";
import { trpc } from "@/lib/trpc/client";

/**
 * Static changelog feed.
 *
 * Inlined here (not a separate `packages/changelog`) because the volume
 * is tiny and we want zero build coupling. Order: newest first. The
 * `version` value is the cursor stored on `users.last_changelog_seen`,
 * so it MUST be unique and monotonic-ish (we don't actually compare
 * versions; we compare against the most-recent entry's version).
 *
 * To add an entry: prepend a new object. The dashboard will pop the
 * modal automatically on next load for any user whose
 * `last_changelog_seen` doesn't match the head entry.
 */
export type ChangelogEntry = {
  version: string;
  /** YYYY-MM-DD; rendered with toLocaleDateString. */
  date: string;
  title: string;
  /** Markdown-ish; we only render paragraph + list-item line breaks. */
  body: string;
  /** Optional /public path or remote URL. */
  screenshot?: string;
};

export const CHANGELOG_ENTRIES: ChangelogEntry[] = [
  {
    version: "2026.04.27-wave15",
    date: "2026-04-27",
    title: "Welcome to the Paper Crane private beta",
    body: [
      "You're one of the first users on Paper Crane. Thanks for kicking the tires.",
      "Highlights this week:",
      "• Invite-only signup with shareable codes",
      "• In-app feedback widget: click the BETA pill in the topbar any time",
      "• /whats-new page so you can scroll back through what shipped",
      "Found something rough? Send us feedback. We read every note.",
    ].join("\n"),
  },
  {
    version: "2026.04.20-wave14",
    date: "2026-04-20",
    title: "Project versioning, annotations, and design tags",
    body: [
      "Designs now have a comment thread, project history is auditable, and you can",
      "tag designs with org-scoped chips for filtering. Forking a project is also live.",
    ].join("\n"),
  },
];

export function getLatestChangelogEntry(): ChangelogEntry | null {
  return CHANGELOG_ENTRIES[0] ?? null;
}

/**
 * Modal shown on dashboard load when the latest entry's `version` does
 * not match the user's `last_changelog_seen`. Dismissal calls
 * `beta.markChangelogSeen` so it stays closed across reloads.
 *
 * The component renders as a no-op while it's loading the user's cursor
 *: we don't pop a flicker before we know whether they've seen it.
 */
export function WhatsNew() {
  const latest = useMemo(() => getLatestChangelogEntry(), []);
  const cursor = trpc.beta.getChangelogCursor.useQuery(undefined, {
    staleTime: 30_000,
    retry: false,
  });
  const mark = trpc.beta.markChangelogSeen.useMutation();

  const [open, setOpen] = useState(false);
  const [dismissedVersion, setDismissedVersion] = useState<string | null>(null);

  useEffect(() => {
    if (!latest) return;
    if (cursor.isLoading || cursor.isError) return;
    const lastSeen = cursor.data?.lastChangelogSeen ?? null;
    if (dismissedVersion === latest.version) return;
    if (lastSeen !== latest.version) setOpen(true);
  }, [latest, cursor.isLoading, cursor.isError, cursor.data, dismissedVersion]);

  if (!latest || !open) return null;

  function dismiss() {
    if (!latest) return;
    setOpen(false);
    setDismissedVersion(latest.version);
    mark.mutate({ version: latest.version });
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="whats-new-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4 py-6"
      onClick={(e) => {
        if (e.target === e.currentTarget) dismiss();
      }}
    >
      <div className="relative w-full max-w-lg overflow-hidden rounded-lg border border-lattice bg-paper shadow-xl">
        <button
          type="button"
          onClick={dismiss}
          aria-label="Close"
          className="absolute right-3 top-3 inline-flex h-8 w-8 items-center justify-center rounded-full text-graphite-soft hover:bg-paper-fold hover:text-ink"
        >
          <X className="h-4 w-4" />
        </button>

        {latest.screenshot && (
          <div className="relative aspect-[16/9] w-full bg-paper-fold">
            <Image
              src={latest.screenshot}
              alt=""
              fill
              sizes="(max-width: 640px) 100vw, 512px"
              className="object-cover"
            />
          </div>
        )}

        <div className="p-6">
          <p className="font-sans text-[12px] text-graphite-soft">
            {new Date(latest.date).toLocaleDateString(undefined, {
              year: "numeric",
              month: "short",
              day: "numeric",
            })}{" "}
            · What's new
          </p>
          <h2 id="whats-new-title" className="mt-2 font-display text-[26px] text-ink">
            {latest.title}
          </h2>
          <div className="mt-3 space-y-2 font-sans text-[14px] leading-relaxed text-graphite">
            {latest.body.split("\n").map((line, i) => (
              <p key={i}>{line}</p>
            ))}
          </div>

          <div className="mt-6 flex items-center justify-between">
            <a
              href="/app/whats-new"
              className="font-sans text-[13px] text-graphite-soft underline decoration-lattice-strong underline-offset-2 hover:text-ink"
            >
              Full changelog →
            </a>
            <button
              type="button"
              onClick={dismiss}
              data-testid="whats-new-dismiss"
              className="btn-primary"
            >
              Got it
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
