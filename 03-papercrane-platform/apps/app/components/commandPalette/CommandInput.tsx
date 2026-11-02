"use client";

import { forwardRef } from "react";

interface CommandInputProps {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void;
}

/**
 * Top-of-modal search field. Borderless, big, mono-ish.
 * The parent (`CommandPalette`) owns the query state and arrow-key handling;
 * we just forward keydown events up via `onKeyDown`.
 */
export const CommandInput = forwardRef<HTMLInputElement, CommandInputProps>(
  function CommandInput(
    { value, onChange, placeholder = "Search or run a command...", onKeyDown },
    ref,
  ) {
    return (
      <div className="flex items-center border-b border-lattice px-4 py-3 dark:border-white/10">
        <svg
          aria-hidden
          className="mr-3 h-4 w-4 text-graphite-soft"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
        <input
          ref={ref}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          spellCheck={false}
          autoComplete="off"
          autoCorrect="off"
          className="w-full bg-transparent text-ink placeholder:text-graphite-soft focus:outline-none dark:text-paper"
          aria-label="Command palette search"
        />
        <kbd className="ml-3 hidden rounded-md border border-lattice px-1.5 py-0.5 font-sans text-[12px] r text-graphite-soft sm:inline-block dark:border-white/10">
          esc
        </kbd>
      </div>
    );
  },
);
