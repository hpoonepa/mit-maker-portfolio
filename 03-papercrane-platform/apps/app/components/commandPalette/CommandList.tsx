"use client";

import { useMemo } from "react";
import type { Command, CommandGroup as Group } from "@/lib/commandPalette/registry";
import { CommandGroup } from "./CommandGroup";
import { CommandItem } from "./CommandItem";
import { CommandEmpty } from "./CommandEmpty";

interface CommandListProps {
  commands: Command[];
  /** id of the visually selected row (may be a recents-prefixed id) */
  activeId: string | null;
  loading: boolean;
  query: string;
  onHover: (id: string) => void;
  onSelect: (cmd: Command) => void;
  /** rendered above the result list (usually <RecentCommands/>) */
  header?: React.ReactNode;
}

/**
 * Scrollable results area. Groups commands by `command.group` in a fixed
 * order and renders a `CommandEmpty` when there are zero matches.
 *
 * Active-row tracking is id-based rather than index-based so that the
 * recents header (which uses the same underlying command ids with a
 * `recent-` prefix) doesn't collide with catalog entries.
 */
const GROUP_ORDER: Group[] = [
  "Navigation",
  "Actions",
  "Projects",
  "Jobs",
  "Targets",
  "Tools",
  "Docs",
  "Recent",
];

export function CommandList({
  commands,
  activeId,
  loading,
  query,
  onHover,
  onSelect,
  header,
}: CommandListProps) {
  const grouped = useMemo(() => groupByOrder(commands), [commands]);

  const hasResults = commands.length > 0;

  return (
    <div
      className="max-h-[60vh] overflow-y-auto px-2 pb-2 pt-1"
      role="listbox"
      aria-label="Command results"
    >
      {header}

      {loading ? <LoadingSkeleton /> : null}

      {!loading && !hasResults && query.trim().length > 0 ? (
        <CommandEmpty query={query} />
      ) : null}

      {hasResults
        ? grouped.map(({ group, items }) => (
            <CommandGroup key={group} heading={group}>
              {items.map((cmd) => (
                <CommandItem
                  key={cmd.id}
                  command={cmd}
                  active={activeId === cmd.id}
                  onSelect={() => onSelect(cmd)}
                  onMouseEnter={() => onHover(cmd.id)}
                />
              ))}
            </CommandGroup>
          ))
        : null}
    </div>
  );
}

function groupByOrder(commands: Command[]): Array<{ group: Group; items: Command[] }> {
  const buckets = new Map<Group, Command[]>();
  for (const cmd of commands) {
    const arr = buckets.get(cmd.group) ?? [];
    arr.push(cmd);
    buckets.set(cmd.group, arr);
  }
  return GROUP_ORDER
    .map((group) => ({ group, items: buckets.get(group) ?? [] }))
    .filter(({ items }) => items.length > 0);
}

function LoadingSkeleton() {
  return (
    <div className="space-y-1 px-2 py-2" aria-hidden>
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="flex items-center gap-3 rounded-md px-1 py-2"
        >
          <div className="h-6 w-6 animate-pulse rounded-md bg-paper-deep dark:bg-white/5" />
          <div className="flex-1 space-y-1">
            <div className="h-3 w-1/3 animate-pulse rounded bg-paper-deep dark:bg-white/5" />
            <div className="h-2 w-1/2 animate-pulse rounded bg-paper-deep/70 dark:bg-white/5" />
          </div>
        </div>
      ))}
    </div>
  );
}
