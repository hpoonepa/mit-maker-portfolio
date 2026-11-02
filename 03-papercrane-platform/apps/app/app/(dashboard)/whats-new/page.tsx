import type { Metadata } from "next";
import {
  CHANGELOG_ENTRIES,
  type ChangelogEntry,
} from "@/components/beta/WhatsNew";

/**
 * Full changelog page: every entry, newest first. Server-rendered from the
 * static `CHANGELOG_ENTRIES` array; the WhatsNew modal pops the head entry
 * automatically on dashboard load and links here for the back-catalogue.
 *
 * Why a separate page instead of just the modal?
 * - Beta testers ask "what changed last week?": sending them /whats-new is
 *   easier than having them re-trigger the modal.
 * - Search-engine and LLM-grade documentation: a stable URL we can link to
 *   from email and changelog tweets.
 *
 * If the entry list grows past ~50 we should split paginate, but for the
 * private beta a single rendered list keeps things simple.
 */

export const metadata: Metadata = {
  title: "What's new: Paper Crane",
  description: "Recent changes to Paper Crane.",
};

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function ChangelogCard({ entry }: { entry: ChangelogEntry }) {
  return (
    <article className="bg-paper p-6">
      <header>
        <p className="font-sans text-[12px] text-graphite-soft">
          {formatDate(entry.date)} · {entry.version}
        </p>
        <h2 className="mt-1 font-display text-[24px] text-ink">{entry.title}</h2>
      </header>
      <div className="mt-3 space-y-2 font-sans text-[14px] leading-relaxed text-graphite">
        {entry.body.split("\n").map((line, i) => (
          <p key={i}>{line}</p>
        ))}
      </div>
    </article>
  );
}

export default function WhatsNewPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6 sm:py-14">
      <header className="mb-8">
        <p className="font-sans text-[12px] text-graphite-soft">
          Changelog
        </p>
        <h1 className="font-display text-[40px] leading-[1.05] text-ink">
          What's new
        </h1>
        <p className="mt-3 max-w-prose font-sans text-[15px] text-graphite">
          A running log of what we've shipped. Got feedback on any of these?
          Click the <span className="font-mono text-[12px]">BETA</span> badge in
          the topbar to send us a note.
        </p>
      </header>

      {CHANGELOG_ENTRIES.length === 0 ? (
        <p className="font-sans text-[14px] text-graphite-soft">
          Nothing here yet.
        </p>
      ) : (
        <div className="flex flex-col gap-5">
          {CHANGELOG_ENTRIES.map((entry) => (
            <ChangelogCard key={entry.version} entry={entry} />
          ))}
        </div>
      )}
    </main>
  );
}
