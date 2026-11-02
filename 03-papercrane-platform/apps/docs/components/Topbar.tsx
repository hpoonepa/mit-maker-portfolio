"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Search } from "lucide-react";

export function Topbar() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  return (
    <header className="sticky top-0 z-30 border-b border-lattice bg-paper/85 backdrop-blur">
      <div className="mx-auto flex w-full max-w-[1480px] items-center justify-between px-6 py-4 sm:px-8 lg:px-12">
        <Link href="/" className="flex items-center gap-2">
          <span
            aria-hidden
            className="inline-block h-3 w-3 rotate-45 bg-crane"
            style={{ clipPath: "polygon(0 50%, 50% 0, 100% 50%, 50% 100%)" }}
          />
          <span className="font-display text-[20px] tracking-tight">Paper Crane</span>
          <span className="ml-2 rounded-full border border-lattice-strong px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.2em] text-graphite">
            Docs
          </span>
        </Link>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="hidden items-center gap-2 rounded-full border border-lattice-strong bg-paper-fold/40 px-3 py-1.5 text-[13px] text-graphite transition-colors hover:border-ink hover:text-ink sm:inline-flex"
          >
            <Search className="h-3.5 w-3.5" />
            <span>Search docs</span>
            <kbd className="ml-3 rounded border border-lattice-strong bg-paper px-1.5 py-0.5 font-mono text-[10px] text-graphite">
              ⌘K
            </kbd>
          </button>
          <Link
            href="https://app.papercrane.bio"
            className="rounded-full bg-ink px-4 py-1.5 text-[13px] text-paper transition-colors hover:bg-crane"
          >
            Open app
          </Link>
        </div>
      </div>

      {open ? (
        <div
          className="fixed inset-0 z-40 flex items-start justify-center bg-ink/40 px-4 pt-32"
          onClick={() => setOpen(false)}
        >
          <div
            className="w-full max-w-xl rounded-2xl border border-lattice-strong bg-paper p-2 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2 border-b border-lattice px-3 py-2">
              <Search className="h-4 w-4 text-graphite" />
              <input
                autoFocus
                placeholder="Search docs (coming soon)…"
                className="flex-1 bg-transparent text-[14px] outline-none placeholder:text-graphite-soft"
              />
              <kbd className="rounded border border-lattice-strong bg-paper-fold px-1.5 py-0.5 font-mono text-[10px] text-graphite">
                Esc
              </kbd>
            </div>
            <div className="px-3 py-4 text-[13px] text-graphite">
              Full-text search ships in the next docs release. For now, use the left nav.
            </div>
          </div>
        </div>
      ) : null}
    </header>
  );
}
