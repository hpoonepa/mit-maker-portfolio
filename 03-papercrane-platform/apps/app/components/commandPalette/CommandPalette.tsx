"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import {
  allStaticCommands,
  type Command,
  type CommandActionContext,
} from "@/lib/commandPalette/registry";
import { fuzzyRank } from "@/lib/commandPalette/fuzzy";
import {
  defaultProviders,
  type SearchProviders,
} from "@/lib/commandPalette/providers";
import { useCommandPalette } from "@/lib/commandPalette/useCommandPalette";
import { CommandInput } from "./CommandInput";
import { CommandList } from "./CommandList";
import { RecentCommands } from "./RecentCommands";

interface CommandPaletteProps {
  /** Optional project context for action-command enablement. */
  currentProjectId?: string;
  /** Optional provider override (e.g. tRPC-backed): falls back to `defaultProviders`. */
  providers?: SearchProviders;
}

const DEBOUNCE_MS = 120;

/**
 * Global command palette. Mount once at the root of the authenticated
 * dashboard layout; the hook wires up the Cmd+K hotkey globally.
 *
 * Rendering model
 * ---------------
 * - Idle (no query): show recents + full static catalog (nav + actions).
 * - Typing: show recents (filtered) + fuzzy-ranked static catalog +
 *   async provider results (projects/jobs/targets/tools/docs).
 * - No matches: render <CommandEmpty/>.
 *
 * Keyboard
 * --------
 *   Cmd/Ctrl+K  -> toggle (hook)
 *   Esc         -> close (hook)
 *   ↑ / ↓       -> move selection
 *   Enter       -> run selected action
 */
export function CommandPalette({
  currentProjectId,
  providers = defaultProviders,
}: CommandPaletteProps) {
  const router = useRouter();
  const {
    open,
    close,
    recents,
    pushRecent,
    clearRecents,
  } = useCommandPalette();

  const [query, setQuery] = useState("");
  const [liveResults, setLiveResults] = useState<Command[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset when closing.
  useEffect(() => {
    if (!open) {
      setQuery("");
      setLiveResults([]);
      setActiveId(null);
    } else {
      // Focus the input on open (next tick; the modal mounts synchronously
      // but the input ref may not be attached until after paint).
      const id = requestAnimationFrame(() => inputRef.current?.focus());
      return () => cancelAnimationFrame(id);
    }
  }, [open]);

  // Static catalog (recomputed when project context changes).
  const staticCatalog = useMemo(
    () => allStaticCommands({ currentProjectId }),
    [currentProjectId],
  );

  // Debounced async fan-out over the live providers.
  useEffect(() => {
    if (!open) return;
    const q = query.trim();
    if (q.length === 0) {
      setLiveResults([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const t = setTimeout(() => {
      let cancelled = false;
      Promise.all([
        providers.projects(q),
        providers.jobs(q),
        providers.targets(q),
        providers.tools(q),
        providers.docs(q),
      ])
        .then((groups) => {
          if (cancelled) return;
          setLiveResults(groups.flat());
        })
        .catch(() => {
          if (!cancelled) setLiveResults([]);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
      return () => {
        cancelled = true;
      };
    }, DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [query, open, providers]);

  // Merge + rank.
  const resolved = useMemo(() => {
    const filteredStatic = fuzzyRank(staticCatalog, query);
    // `liveResults` already reflects the current query; we still run fuzzyRank
    // on them to get a consistent ordering against the same scoring function.
    const filteredLive = fuzzyRank(liveResults, query);
    const seen = new Set<string>();
    const merged: Command[] = [];
    for (const cmd of [...filteredStatic, ...filteredLive]) {
      if (seen.has(cmd.id)) continue;
      seen.add(cmd.id);
      merged.push(cmd);
    }
    return merged;
  }, [staticCatalog, liveResults, query]);

  // Build an id -> command lookup for recents resolution.
  const lookup = useMemo(() => {
    const m = new Map<string, Command>();
    for (const cmd of [...staticCatalog, ...liveResults]) m.set(cmd.id, cmd);
    return m;
  }, [staticCatalog, liveResults]);

  // Default selection: first result (or first recent when query is empty).
  useEffect(() => {
    if (!open) return;
    if (query.trim().length === 0 && recents.length > 0) {
      setActiveId(`recent-${recents[0]?.id ?? ""}`);
    } else if (resolved.length > 0) {
      setActiveId(resolved[0]?.id ?? null);
    } else {
      setActiveId(null);
    }
  }, [open, query, resolved, recents]);

  // Flat navigable list = recents (when idle) + resolved results.
  const navigable = useMemo(() => {
    const items: Array<{ id: string; command: Command }> = [];
    if (query.trim().length === 0) {
      for (const r of recents.slice(0, 5)) {
        const cmd = lookup.get(r.id);
        if (cmd) items.push({ id: `recent-${r.id}`, command: cmd });
      }
    }
    for (const cmd of resolved) items.push({ id: cmd.id, command: cmd });
    return items;
  }, [recents, resolved, lookup, query]);

  const execute = useCallback(
    (cmd: Command) => {
      const ctx: CommandActionContext = {
        router: { push: (p) => router.push(p) },
      };
      pushRecent({ id: cmd.id, title: cmd.title, group: cmd.group });
      close();
      // Defer action so close animation (if any) and state clear run first.
      queueMicrotask(() => {
        try {
          void cmd.action(ctx);
        } catch {
          /* swallow: action implementations own their own error UX */
        }
      });
    },
    [close, pushRecent, router],
  );

  const moveSelection = useCallback(
    (delta: 1 | -1) => {
      if (navigable.length === 0) return;
      const idx = navigable.findIndex((n) => n.id === activeId);
      const next =
        idx === -1
          ? 0
          : (idx + delta + navigable.length) % navigable.length;
      setActiveId(navigable[next]?.id ?? null);
    },
    [navigable, activeId],
  );

  const onInputKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        moveSelection(1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        moveSelection(-1);
      } else if (e.key === "Enter") {
        e.preventDefault();
        const entry = navigable.find((n) => n.id === activeId);
        if (entry) execute(entry.command);
      }
    },
    [moveSelection, navigable, activeId, execute],
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[18vh]"
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
      <div className="relative w-full max-w-[640px] overflow-hidden rounded-xl border border-lattice bg-paper shadow-2xl dark:border-white/10 dark:bg-ink">
        <CommandInput
          ref={inputRef}
          value={query}
          onChange={setQuery}
          onKeyDown={onInputKeyDown}
        />
        <CommandList
          commands={resolved}
          activeId={activeId}
          loading={loading}
          query={query}
          onHover={setActiveId}
          onSelect={execute}
          header={
            query.trim().length === 0 ? (
              <RecentCommands
                recents={recents}
                lookup={lookup}
                activeId={activeId}
                onHover={setActiveId}
                onSelect={execute}
                onClear={clearRecents}
              />
            ) : null
          }
        />
        <footer className="flex items-center justify-between border-t border-lattice px-3 py-2 text-[10px] uppercase tracking-wider text-graphite-soft dark:border-white/10">
          <span className="font-mono">paper crane · cmd-k</span>
          <span className="flex items-center gap-2">
            <Shortcut label="navigate" keys={["↑", "↓"]} />
            <Shortcut label="run" keys={["↵"]} />
            <Shortcut label="close" keys={["esc"]} />
          </span>
        </footer>
      </div>
    </div>
  );
}

function Shortcut({ label, keys }: { label: string; keys: string[] }) {
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

export default CommandPalette;
