"use client";

/**
 * A single row in the palette. Visual states:
 *   - active   (keyboard or hover)   → highlighted background
 *   - default  → plain
 *
 * Stays display-only; selection + execution live in `CommandPalette`.
 */

import type { ReactNode } from "react";

export interface CommandItemProps {
  id: string;
  title: string;
  subtitle?: string | null;
  shortcut?: string | null;
  icon?: ReactNode;
  active: boolean;
  onHover: (id: string) => void;
  onSelect: () => void;
}

export function CommandItem({
  id,
  title,
  subtitle,
  shortcut,
  icon,
  active,
  onHover,
  onSelect,
}: CommandItemProps) {
  return (
    <button
      type="button"
      data-command-id={id}
      onMouseEnter={() => onHover(id)}
      onClick={onSelect}
      className={[
        "group flex w-full items-center justify-between gap-3 px-3 py-2 text-left transition-colors",
        active
          ? "bg-paper-fold text-ink dark:bg-white/10 dark:text-paper"
          : "text-graphite hover:bg-paper-fold/60 dark:text-paper/80 dark:hover:bg-white/5",
      ].join(" ")}
    >
      <span className="flex min-w-0 items-center gap-3">
        {icon ? (
          <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md border border-lattice bg-paper text-graphite dark:border-white/10 dark:bg-white/5 dark:text-paper/70">
            {icon}
          </span>
        ) : null}
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium">{title}</span>
          {subtitle ? (
            <span className="block truncate text-[11px] text-graphite-soft dark:text-paper/50">
              {subtitle}
            </span>
          ) : null}
        </span>
      </span>
      {shortcut ? (
        <span className="ml-3 hidden shrink-0 font-sans text-[12px] r text-graphite-soft sm:inline">
          {shortcut}
        </span>
      ) : null}
    </button>
  );
}

export default CommandItem;
