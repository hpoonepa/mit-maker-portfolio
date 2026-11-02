"use client";

import type {
  RecentCommandEntry,
} from "@/lib/commandPalette/useCommandPalette";
import type { Command } from "@/lib/commandPalette/registry";
import { CommandGroup } from "./CommandGroup";
import { CommandItem } from "./CommandItem";

interface RecentCommandsProps {
  recents: RecentCommandEntry[];
  /** Full catalog keyed by id, used to resolve the callable action. */
  lookup: Map<string, Command>;
  activeId: string | null;
  onHover: (id: string) => void;
  onSelect: (cmd: Command) => void;
  onClear: () => void;
}

/**
 * Renders the last 5 used commands as a "Recent" group. We keep up to 8 in
 * storage (see `useCommandPalette`) but surface only the top 5 so the group
 * stays visually tight above the static catalog.
 */
const VISIBLE_RECENTS = 5;

export function RecentCommands({
  recents,
  lookup,
  activeId,
  onHover,
  onSelect,
  onClear,
}: RecentCommandsProps) {
  if (recents.length === 0) return null;

  const resolved = recents
    .slice(0, VISIBLE_RECENTS)
    .map((r) => lookup.get(r.id))
    .filter((cmd): cmd is Command => Boolean(cmd));

  if (resolved.length === 0) return null;

  return (
    <CommandGroup heading="Recent">
      {resolved.map((cmd) => (
        <CommandItem
          key={`recent-${cmd.id}`}
          command={cmd}
          active={activeId === `recent-${cmd.id}`}
          onSelect={() => onSelect(cmd)}
          onMouseEnter={() => onHover(`recent-${cmd.id}`)}
        />
      ))}
      <button
        type="button"
        onClick={onClear}
        className="mt-1 self-end px-3 pb-1 text-[10px] uppercase tracking-wider text-graphite-soft hover:text-crane"
      >
        clear
      </button>
    </CommandGroup>
  );
}
