"use client";

/**
 * Section header + container for a group of `CommandItem`s.
 *
 * Renders nothing if the group has zero children: keeps the palette
 * tidy when a category has no matches.
 */

import type { ReactNode } from "react";

export interface CommandGroupProps {
  heading: string;
  /** Optional small action rendered on the right (e.g. "Clear"). */
  trailing?: ReactNode;
  children: ReactNode;
  /** Skip the heading row when no children are present. */
  hideWhenEmpty?: boolean;
  empty?: boolean;
}

export function CommandGroup({
  heading,
  trailing,
  children,
  hideWhenEmpty = true,
  empty = false,
}: CommandGroupProps) {
  if (hideWhenEmpty && empty) return null;
  return (
    <div className="border-t border-lattice py-1 first:border-t-0 dark:border-white/10">
      <div className="flex items-center justify-between px-3 pt-2 pb-1 font-sans text-[12px] text-graphite-soft">
        <span>{heading}</span>
        {trailing}
      </div>
      <div className="flex flex-col">{children}</div>
    </div>
  );
}

export default CommandGroup;
