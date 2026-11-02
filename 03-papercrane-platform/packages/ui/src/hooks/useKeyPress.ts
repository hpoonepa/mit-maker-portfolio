import { useEffect, useRef } from "react";

export interface UseKeyPressOptions {
  /** Attach on capture phase. */
  capture?: boolean;
  /** Require meta/ctrl modifier. */
  meta?: boolean;
  /** Require shift modifier. */
  shift?: boolean;
  /** Require alt modifier. */
  alt?: boolean;
  /** Disable the listener without unmounting. */
  enabled?: boolean;
  /** Event target (default `window`). */
  target?: Window | Document | HTMLElement | null;
  /** Prevent default when match. */
  preventDefault?: boolean;
}

type KeyMatch = string | string[] | ((e: KeyboardEvent) => boolean);

function matches(e: KeyboardEvent, match: KeyMatch): boolean {
  if (typeof match === "function") return match(e);
  if (Array.isArray(match)) return match.some((k) => k.toLowerCase() === e.key.toLowerCase());
  return match.toLowerCase() === e.key.toLowerCase();
}

/**
 * Bind a keyboard shortcut to a handler. Returns nothing.
 *
 * @example
 * useKeyPress("Escape", () => setOpen(false));
 * useKeyPress("k", runSearch, { meta: true });
 */
export function useKeyPress(
  key: KeyMatch,
  handler: (e: KeyboardEvent) => void,
  options: UseKeyPressOptions = {}
): void {
  const handlerRef = useRef(handler);
  useEffect(() => {
    handlerRef.current = handler;
  }, [handler]);

  useEffect(() => {
    if (options.enabled === false) return;
    const target =
      options.target ?? (typeof window !== "undefined" ? window : null);
    if (!target) return;

    const onKey = (ev: Event) => {
      const e = ev as KeyboardEvent;
      if (!matches(e, key)) return;
      if (options.meta && !(e.metaKey || e.ctrlKey)) return;
      if (options.shift && !e.shiftKey) return;
      if (options.alt && !e.altKey) return;
      if (options.preventDefault) e.preventDefault();
      handlerRef.current(e);
    };

    target.addEventListener("keydown", onKey, options.capture ?? false);
    return () => target.removeEventListener("keydown", onKey, options.capture ?? false);
  }, [
    key,
    options.capture,
    options.meta,
    options.shift,
    options.alt,
    options.enabled,
    options.target,
    options.preventDefault,
  ]);
}
