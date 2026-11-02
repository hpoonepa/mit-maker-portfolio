"use client";

/**
 * Cmd+K command palette for the dashboard.
 *
 * Composition:
 *   - SearchProvider owns open/close + recents + the global hotkey.
 *   - This component is mounted lazily by SearchProvider (only when open).
 *   - Quick actions come from `lib/command/registry`.
 *   - Live entity hits come from `trpc.search.combined`.
 *
 * Inline filters in the input drive the `filter` parameter sent to tRPC:
 *   `proj:foo`, `job:abc`, `design:M..`, `@alice`.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { trpc } from "@/lib/trpc/client";
import {
  quickActions,
  scoreCommand,
  type Command,
  type CommandActionContext,
} from "@/lib/command/registry";
import { useSearch } from "./SearchProvider";
import { CommandGroup } from "./CommandGroup";
import { CommandItem } from "./CommandItem";

const DEBOUNCE_MS = 200;

type Filter = "all" | "project" | "job" | "design" | "person";

interface ParsedQuery {
  filter: Filter;
  text: string;
}

function parseQuery(raw: string): ParsedQuery {
  const trimmed = raw.trimStart();
  if (trimmed.startsWith("proj:")) {
    return { filter: "project", text: trimmed.slice(5).trim() };
  }
  if (trimmed.startsWith("job:")) {
    return { filter: "job", text: trimmed.slice(4).trim() };
  }
  if (trimmed.startsWith("design:")) {
    return { filter: "design", text: trimmed.slice(7).trim() };
  }
  if (trimmed.startsWith("@")) {
    return { filter: "person", text: trimmed.slice(1).trim() };
  }
  return { filter: "all", text: trimmed };
}

interface FlatRow {
  id: string;
  group: string;
  title: string;
  subtitle?: string | null;
  shortcut?: string | null;
  onSelect: () => void;
}

export function CommandPalette() {
  const { setOpen, recents, pushRecent, clearRecents, currentProjectSlug } =
    useSearch();
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  const [raw, setRaw] = useState("");
  const [debounced, setDebounced] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);

  // Focus input on mount.
  useEffect(() => {
    const id = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, []);

  // Debounce the typed query.
  useEffect(() => {
    const t = setTimeout(() => setDebounced(raw), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [raw]);

  const parsed = useMemo(() => parseQuery(debounced), [debounced]);
  const enabled = parsed.text.length > 0;

  const search = trpc.search.combined.useQuery(
    { q: parsed.text, filter: parsed.filter },
    { enabled, staleTime: 30_000 },
  );

  const close = useCallback(() => setOpen(false), [setOpen]);

  const signOut = useCallback(async () => {
    try {
      await fetch("/api/auth/sign-out", { method: "POST" });
    } catch {
      /* ignore */
    }
    router.push("/login");
  }, [router]);

  const runCommand = useCallback(
    (cmd: Command) => {
      const ctx: CommandActionContext = {
        router: { push: (href) => router.push(href) },
        signOut,
        currentProjectSlug,
      };
      pushRecent({
        id: cmd.id,
        title: cmd.title,
        href: "",
        group: cmd.group,
      });
      close();
      queueMicrotask(() => {
        try {
          void cmd.action(ctx);
        } catch {
          /* swallow */
        }
      });
    },
    [router, signOut, currentProjectSlug, pushRecent, close],
  );

  const navigateTo = useCallback(
    (item: { id: string; title: string; href: string; group: string }) => {
      pushRecent(item);
      close();
      queueMicrotask(() => router.push(item.href));
    },
    [router, pushRecent, close],
  );

  // Filter quick actions against the typed text (ignored when a kind filter
  // is active: those slots are reserved for entity results).
  const actions = useMemo(() => {
    if (parsed.filter !== "all") return [] as Command[];
    const all = quickActions({ currentProjectSlug });
    if (parsed.text.length === 0) return all;
    return all
      .map((cmd) => ({ cmd, score: scoreCommand(cmd, parsed.text) }))
      .filter((x) => x.score >= 0)
      .sort((a, b) => b.score - a.score)
      .map((x) => x.cmd);
  }, [parsed, currentProjectSlug]);

  // Build the flat navigable list (in render order).
  const rows = useMemo<FlatRow[]>(() => {
    const list: FlatRow[] = [];

    // 1. Recents only when query is empty.
    if (parsed.text.length === 0) {
      for (const r of recents) {
        list.push({
          id: `recent-${r.id}`,
          group: "Recent",
          title: r.title,
          subtitle: r.group,
          onSelect: () =>
            r.href
              ? navigateTo({
                  id: r.id,
                  title: r.title,
                  href: r.href,
                  group: r.group,
                })
              : close(),
        });
      }
    }

    for (const cmd of actions) {
      list.push({
        id: cmd.id,
        group: "Actions",
        title: cmd.title,
        subtitle: cmd.subtitle,
        shortcut: cmd.shortcut,
        onSelect: () => runCommand(cmd),
      });
    }

    const data = search.data;
    if (data) {
      for (const p of data.projects) {
        list.push({
          id: `project-${p.id}`,
          group: "Projects",
          title: p.title,
          subtitle: p.subtitle,
          onSelect: () =>
            navigateTo({
              id: p.id,
              title: p.title,
              href: p.href,
              group: "Projects",
            }),
        });
      }
      for (const j of data.jobs) {
        list.push({
          id: `job-${j.id}`,
          group: "Jobs",
          title: j.title,
          subtitle: j.subtitle,
          onSelect: () =>
            navigateTo({
              id: j.id,
              title: j.title,
              href: j.href,
              group: "Jobs",
            }),
        });
      }
      for (const d of data.designs) {
        list.push({
          id: `design-${d.id}`,
          group: "Designs",
          title: d.title,
          subtitle: d.subtitle,
          onSelect: () =>
            navigateTo({
              id: d.id,
              title: d.title,
              href: d.href,
              group: "Designs",
            }),
        });
      }
      for (const u of data.people) {
        list.push({
          id: `person-${u.id}`,
          group: "People",
          title: u.title,
          subtitle: u.subtitle,
          onSelect: () =>
            navigateTo({
              id: u.id,
              title: u.title,
              href: u.href,
              group: "People",
            }),
        });
      }
    }

    return list;
  }, [parsed.text, recents, actions, search.data, runCommand, navigateTo, close]);

  // Default selection.
  useEffect(() => {
    if (rows.length === 0) {
      setActiveId(null);
      return;
    }
    if (!rows.find((r) => r.id === activeId)) {
      setActiveId(rows[0]!.id);
    }
  }, [rows, activeId]);

  const moveSelection = useCallback(
    (delta: 1 | -1) => {
      if (rows.length === 0) return;
      const idx = rows.findIndex((r) => r.id === activeId);
      const next =
        idx === -1 ? 0 : (idx + delta + rows.length) % rows.length;
      setActiveId(rows[next]!.id);
    },
    [rows, activeId],
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        moveSelection(1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        moveSelection(-1);
      } else if (e.key === "Enter") {
        e.preventDefault();
        const row = rows.find((r) => r.id === activeId);
        if (row) row.onSelect();
      } else if (e.key === "Escape") {
        e.preventDefault();
        close();
      }
    },
    [moveSelection, rows, activeId, close],
  );

  // Group rows for rendering.
  const grouped = useMemo(() => {
    const map = new Map<string, FlatRow[]>();
    for (const row of rows) {
      if (!map.has(row.group)) map.set(row.group, []);
      map.get(row.group)!.push(row);
    }
    return map;
  }, [rows]);

  const order = ["Recent", "Actions", "Projects", "Jobs", "Designs", "People"];
  const isLoading = enabled && search.isFetching;
  const isEmpty = !isLoading && rows.length === 0;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center px-4 pt-[16vh]"
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
    >
      <button
        type="button"
        aria-label="Close command palette"
        onClick={close}
        className="absolute inset-0 bg-ink/40 dark:bg-black/60"
      />
      <div className="relative w-full max-w-[600px] overflow-hidden rounded-lg border border-lattice-strong bg-paper shadow-2xl ring-1 ring-black/5 dark:border-white/10 dark:bg-ink dark:ring-white/5">
        <div className="flex items-center gap-3 border-b border-lattice px-4 py-3 dark:border-white/10">
          <SearchGlyph />
          <input
            ref={inputRef}
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search projects, jobs, designs, or people…"
            className="w-full bg-transparent text-sm text-ink placeholder:text-graphite-soft focus:outline-none dark:text-paper"
            spellCheck={false}
            autoComplete="off"
          />
          <kbd className="rounded-md border border-lattice bg-paper-fold px-1.5 py-[1px] font-sans text-[12px] r text-graphite-soft dark:border-white/10 dark:bg-white/5">
            esc
          </kbd>
        </div>

        <div className="max-h-[60vh] overflow-y-auto">
          {isLoading ? (
            <SearchSkeleton />
          ) : isEmpty ? (
            <EmptyState />
          ) : (
            order.map((heading) => {
              const items = grouped.get(heading);
              if (!items || items.length === 0) return null;
              const trailing =
                heading === "Recent" ? (
                  <button
                    type="button"
                    onClick={clearRecents}
                    className="text-[10px] uppercase tracking-wider text-graphite-soft hover:text-ink dark:hover:text-paper"
                  >
                    clear
                  </button>
                ) : null;
              return (
                <CommandGroup
                  key={heading}
                  heading={heading}
                  trailing={trailing}
                >
                  {items.map((row) => (
                    <CommandItem
                      key={row.id}
                      id={row.id}
                      title={row.title}
                      subtitle={row.subtitle}
                      shortcut={row.shortcut}
                      active={row.id === activeId}
                      onHover={setActiveId}
                      onSelect={row.onSelect}
                    />
                  ))}
                </CommandGroup>
              );
            })
          )}
        </div>

        <Footer />
      </div>
    </div>
  );
}

function Footer(): ReactNode {
  return (
    <footer className="flex items-center justify-between border-t border-lattice px-3 py-2 text-[10px] uppercase tracking-wider text-graphite-soft dark:border-white/10">
      <span className="font-mono">paper crane · cmd-k</span>
      <span className="flex items-center gap-3">
        <Hint label="navigate" keys={["↑", "↓"]} />
        <Hint label="open" keys={["↵"]} />
        <Hint label="filter" keys={["proj:", "job:", "@"]} />
      </span>
    </footer>
  );
}

function Hint({ label, keys }: { label: string; keys: string[] }) {
  return (
    <span className="inline-flex items-center gap-1">
      {keys.map((k) => (
        <kbd
          key={k}
          className="rounded-md border border-lattice bg-paper-fold px-1 py-[1px] font-mono text-[10px] text-graphite dark:border-white/10 dark:bg-white/5 dark:text-paper/70"
        >
          {k}
        </kbd>
      ))}
      <span>{label}</span>
    </span>
  );
}

function SearchGlyph() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden
      className="text-graphite-soft"
    >
      <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.4" />
      <path
        d="M11 11l3 3"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

function SearchSkeleton() {
  return (
    <div className="flex flex-col gap-2 p-3">
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className="flex items-center gap-3 rounded-md px-2 py-2"
        >
          <div className="h-6 w-6 shrink-0 animate-pulse rounded-md bg-paper-fold dark:bg-white/5" />
          <div className="flex-1 space-y-1.5">
            <div className="h-3 w-1/3 animate-pulse rounded bg-paper-fold dark:bg-white/5" />
            <div className="h-2 w-1/2 animate-pulse rounded bg-paper-fold/70 dark:bg-white/5" />
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-1 px-6 py-10 text-center">
      <p className="text-sm font-medium text-ink dark:text-paper">No results</p>
      <p className="max-w-[36ch] text-[12px] text-graphite-soft">
        Try a project name, a job ID, or a sequence preview. Use{" "}
        <code className="font-mono">proj:</code>,{" "}
        <code className="font-mono">job:</code>,{" "}
        <code className="font-mono">design:</code>, or{" "}
        <code className="font-mono">@user</code> to narrow.
      </p>
    </div>
  );
}

export default CommandPalette;
