"use client";

import type { Command } from "@/lib/commandPalette/registry";

interface CommandItemProps {
  command: Command;
  active: boolean;
  onSelect: () => void;
  onMouseEnter: () => void;
}

/**
 * A single selectable row. The parent list owns "which index is active"
 * and passes `active=true` for the highlighted entry: we never manage
 * focus ourselves, because the input stays focused while the list is
 * navigated with arrow keys.
 */
export function CommandItem({
  command,
  active,
  onSelect,
  onMouseEnter,
}: CommandItemProps) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={active}
      onMouseEnter={onMouseEnter}
      onMouseDown={(e) => {
        // Prevent the input from losing focus before `click` fires.
        e.preventDefault();
      }}
      onClick={onSelect}
      className={[
        "group flex w-full items-center gap-3 rounded-md px-3 py-2 text-left transition-colors",
        active
          ? "bg-crane-glow text-ink dark:text-paper"
          : "text-ink-soft hover:bg-paper-fold dark:text-paper/80 dark:hover:bg-white/5",
      ].join(" ")}
    >
      <span
        className={[
          "flex h-6 w-6 shrink-0 items-center justify-center rounded-md border text-[11px] font-mono",
          active
            ? "border-crane bg-crane/10 text-crane dark:border-crane/60"
            : "border-lattice text-graphite-soft dark:border-white/10",
        ].join(" ")}
        aria-hidden
      >
        {iconGlyph(command.icon)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">
          {command.title}
        </span>
        {command.subtitle ? (
          <span className="block truncate text-xs text-graphite-soft">
            {command.subtitle}
          </span>
        ) : null}
      </span>
      {active ? (
        <kbd className="rounded-md border border-lattice bg-paper px-1.5 py-0.5 font-mono text-[10px] text-graphite dark:border-white/10 dark:bg-white/5 dark:text-paper/70">
          ↵
        </kbd>
      ) : null}
    </button>
  );
}

/**
 * Tiny fallback glyph picker. Real implementation should render `lucide-react`
 * icons keyed by `command.icon`. We avoid pulling lucide here to keep this
 * file dependency-free; the parent dashboard layout can swap this out for
 * a proper icon map.
 */
function iconGlyph(icon?: string): string {
  if (!icon) return "•";
  // First meaningful letter of the icon name, uppercased.
  return icon.charAt(0).toUpperCase();
}
