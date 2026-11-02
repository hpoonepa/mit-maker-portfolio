"use client";

import { useCallback, useEffect, useState } from "react";
import { BookmarkPlus, Bookmark, Trash2, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export interface SavedView<T> {
  id: string;
  name: string;
  state: T;
  createdAt: number;
}

export interface SavedViewsProps<T> {
  /** Page key for namespacing in localStorage (e.g. "jobs", "designs"). */
  pageKey: string;
  /** Optional user id for per-user namespacing. */
  userId?: string;
  /** Current filter state: what would be saved if the user names a view. */
  current: T;
  /** Apply a saved view's state. */
  onApply: (state: T) => void;
  /** Disable save button when filters match defaults. */
  canSave?: boolean;
  className?: string;
}

function storageKey(pageKey: string, userId?: string): string {
  return `papercrane:saved-views:${userId ?? "anon"}:${pageKey}`;
}

function readViews<T>(pageKey: string, userId?: string): SavedView<T>[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(storageKey(pageKey, userId));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as SavedView<T>[];
  } catch {
    return [];
  }
}

function writeViews<T>(
  pageKey: string,
  userId: string | undefined,
  views: SavedView<T>[],
): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      storageKey(pageKey, userId),
      JSON.stringify(views),
    );
  } catch {
    // quota or privacy mode: silently degrade
  }
}

export function SavedViews<T>({
  pageKey,
  userId,
  current,
  onApply,
  canSave = true,
  className,
}: SavedViewsProps<T>) {
  const [views, setViews] = useState<SavedView<T>[]>([]);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [naming, setNaming] = useState(false);
  const [draftName, setDraftName] = useState("");

  // Lazy load from localStorage after mount.
  useEffect(() => {
    setViews(readViews<T>(pageKey, userId));
  }, [pageKey, userId]);

  const persist = useCallback(
    (next: SavedView<T>[]) => {
      setViews(next);
      writeViews(pageKey, userId, next);
    },
    [pageKey, userId],
  );

  const handleSave = () => {
    const trimmed = draftName.trim();
    if (!trimmed) return;
    const next: SavedView<T> = {
      id:
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      name: trimmed,
      state: current,
      createdAt: Date.now(),
    };
    persist([next, ...views].slice(0, 20));
    setNaming(false);
    setDraftName("");
    setOpen(false);
  };

  const handleDelete = (id: string) => {
    persist(views.filter((v) => v.id !== id));
  };

  return (
    <div className={cn("relative inline-flex", className)}>
      <div className="inline-flex items-center gap-1.5 bg-paper">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-haspopup="listbox"
          aria-expanded={open}
          className="inline-flex items-center gap-1.5 px-3 py-3 font-sans text-[13px] text-graphite hover:text-ink transition-colors"
        >
          <Bookmark className="h-3 w-3" />
          Views
          {views.length > 0 && (
            <span className="font-mono text-[10px] text-graphite-soft tabular-nums">
              {views.length}
            </span>
          )}
          <ChevronDown
            className={cn(
              "h-3 w-3 transition-transform",
              open && "rotate-180",
            )}
          />
        </button>
      </div>

      {open && (
        <div
          role="listbox"
          aria-label="Saved views"
          className="absolute right-0 top-[calc(100%+6px)] z-30 w-72 rounded-lg border border-lattice bg-paper p-2 shadow-soft"
        >
          {views.length === 0 && !naming && (
            <p className="px-3 py-3 font-sans text-[12px] text-graphite-soft">
              No saved views yet.
            </p>
          )}
          {views.length > 0 && (
            <div className="flex items-center justify-between px-2 pb-1">
              <span className="font-sans text-[12px] text-graphite-soft">
                Saved
              </span>
              <button
                type="button"
                onClick={() => setEditing((e) => !e)}
                className="font-sans text-[11px] text-graphite hover:text-ink transition-colors"
              >
                {editing ? "Done" : "Edit"}
              </button>
            </div>
          )}
          <ul className="max-h-64 overflow-y-auto">
            {views.map((v) => (
              <li
                key={v.id}
                className="flex items-center gap-1 rounded-lg px-1 py-0.5 hover:bg-paper-fold/60"
              >
                <button
                  type="button"
                  role="option"
                  aria-selected="false"
                  onClick={() => {
                    onApply(v.state);
                    setOpen(false);
                  }}
                  className="flex-1 truncate px-2 py-1.5 text-left font-sans text-[13px] text-ink"
                >
                  {v.name}
                </button>
                {editing && (
                  <button
                    type="button"
                    onClick={() => handleDelete(v.id)}
                    aria-label={`Delete ${v.name}`}
                    className="rounded p-1 text-graphite-soft hover:text-crane-deep transition-colors"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </li>
            ))}
          </ul>

          <div className="mt-1 pt-2">
            {!naming ? (
              <button
                type="button"
                onClick={() => setNaming(true)}
                disabled={!canSave}
                className={cn(
                  "inline-flex w-full items-center gap-2 rounded-lg px-2 py-1.5 font-sans text-[13px] transition-colors",
                  canSave
                    ? "text-ink hover:bg-paper-fold"
                    : "text-graphite-soft cursor-not-allowed",
                )}
              >
                <BookmarkPlus className="h-3.5 w-3.5" />
                Save current filters as…
              </button>
            ) : (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleSave();
                }}
                className="flex gap-1.5 px-1"
              >
                <input
                  autoFocus
                  type="text"
                  value={draftName}
                  onChange={(e) => setDraftName(e.target.value)}
                  placeholder="View name"
                  className="flex-1 rounded-lg border border-lattice bg-paper px-2 py-1 font-sans text-[13px] text-ink focus:outline-none focus:border-ink"
                  maxLength={60}
                />
                <button
                  type="submit"
                  className="rounded-lg bg-ink px-3 py-1 font-sans text-[12px] text-paper hover:bg-graphite transition-colors"
                >
                  Save
                </button>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
