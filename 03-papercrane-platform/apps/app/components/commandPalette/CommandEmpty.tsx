"use client";

interface CommandEmptyProps {
  query: string;
}

/**
 * Rendered when the current query matches nothing across every provider.
 * Deliberately calm; the palette is an interrupt surface and we don't want
 * it to shout.
 */
export function CommandEmpty({ query }: CommandEmptyProps) {
  return (
    <div className="px-6 py-10 text-center">
      <p className="text-sm text-ink-soft dark:text-paper/80">
        No matches for{" "}
        <span className="font-mono text-crane">
          {query.length > 32 ? query.slice(0, 32) + "…" : query}
        </span>
      </p>
      <p className="mt-1 text-xs text-graphite-soft">
        Try a different query, or press{" "}
        <kbd className="rounded-md border border-lattice px-1 py-0.5 font-mono text-[10px] dark:border-white/10">
          esc
        </kbd>{" "}
        to close.
      </p>
    </div>
  );
}
