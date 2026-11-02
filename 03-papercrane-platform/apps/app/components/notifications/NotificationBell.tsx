"use client";

import { Bell } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { formatUnreadBadge, useUnreadCount } from "@/lib/notifications/hooks";
import { NotificationDropdown } from "./NotificationDropdown";
import { NotificationToast } from "./NotificationToast";

/**
 * Bell-icon entry point that mounts in the TopBar.
 *
 * Behavior:
 *   - red dot when unread > 0, swaps to a number badge (capped at "9+")
 *     once unread > 9: keeps the badge visually compact in the header
 *   - clicking toggles the dropdown (NotificationDropdown owns layout)
 *   - Escape and outside click close the popover
 *   - mounts <NotificationToast/> so realtime inserts surface as toasts
 *     globally regardless of whether the popover is open
 *
 * Reads `useUnreadCount()` from the shared notifications hook layer so
 * marking-read in any other surface (full page, list) propagates here
 * via the tRPC query cache invalidation.
 */
export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const unread = useUnreadCount();

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Compact badge for the header: dot if 1-9, "9+" if >9 (per spec).
  const showBadge = unread > 0;
  const badgeText = unread > 9 ? "9+" : formatUnreadBadge(unread);
  const numericBadge = unread > 9;

  return (
    <>
      <NotificationToast />
      <div className="relative" ref={wrapRef}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-label={
            unread > 0 ? `Notifications (${unread} unread)` : "Notifications"
          }
          aria-expanded={open}
          aria-haspopup="dialog"
          className="relative inline-flex h-9 w-9 items-center justify-center rounded-full text-graphite transition-colors hover:text-ink hover:bg-paper-fold"
        >
          <Bell className="h-4 w-4" aria-hidden />
          {showBadge && (
            <span
              aria-hidden
              className={
                numericBadge
                  ? "absolute -top-1 -right-1 inline-flex min-w-[18px] items-center justify-center rounded-full bg-crane-deep px-1 font-mono text-[10px] leading-[16px] text-paper"
                  : "absolute top-1.5 right-1.5 inline-block h-2 w-2 rounded-full bg-crane-deep ring-2 ring-paper"
              }
            >
              {numericBadge ? badgeText : null}
            </span>
          )}
        </button>

        {open && <NotificationDropdown onClose={() => setOpen(false)} />}
      </div>
    </>
  );
}
