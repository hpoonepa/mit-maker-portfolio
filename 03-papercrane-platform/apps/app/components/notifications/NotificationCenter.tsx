"use client";

import { Bell, Check } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  formatUnreadBadge,
  useMarkRead,
  useUnreadCount,
} from "@/lib/notifications/hooks";
import { useNotificationsRealtime } from "@/lib/notifications/realtime";
import { NotificationList } from "./NotificationList";

/**
 * Bell-icon popover that mounts into the TopBar.
 *
 * Behavior:
 *   - a red dot appears over the bell when unread count > 0
 *   - the dot becomes a number badge that caps at "99+"
 *   - clicking toggles the popover (max-width 384px, anchored top-right)
 *   - Escape closes; outside click closes; Arrow keys inside list navigate
 *
 * `userId` is optional so the component can render during SSR with no
 * data; realtime wiring kicks in once the id is known.
 */
type Props = {
  userId?: string | null;
};

export function NotificationCenter({ userId = null }: Props) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const unread = useUnreadCount();
  const { markAllRead, isMarking } = useMarkRead();

  useNotificationsRealtime(userId ?? null);

  // Outside-click + Escape dismissal.
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

  const badge = formatUnreadBadge(unread);

  return (
    <div className="relative" ref={wrapRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={unread > 0 ? `Notifications (${unread} unread)` : "Notifications"}
        aria-expanded={open}
        aria-haspopup="dialog"
        className="relative inline-flex h-9 w-9 items-center justify-center rounded-full border border-lattice bg-paper text-ink transition-colors hover:border-lattice-strong"
      >
        <Bell className="h-4 w-4" aria-hidden />
        {unread > 0 && (
          <span
            aria-hidden
            className="absolute -top-0.5 -right-0.5 inline-flex min-w-[16px] items-center justify-center rounded-full bg-crane-deep px-1 font-mono text-[10px] leading-[14px] text-paper"
          >
            {badge}
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Notifications"
          className="absolute right-0 top-full z-40 mt-2 w-96 rounded-lg border border-lattice bg-paper shadow-lg"
        >
          <header className="flex items-center justify-between border-b border-lattice px-4 py-3">
            <div>
              <div className="font-sans text-[13px] font-medium text-ink">
                Notifications
              </div>
              <div className="font-sans text-[12px] r text-graphite-soft">
                {unread === 0 ? "all caught up" : `${unread} unread`}
              </div>
            </div>
            <button
              type="button"
              onClick={() => markAllRead().catch(() => {})}
              disabled={isMarking || unread === 0}
              className="inline-flex items-center gap-1.5 rounded-full border border-lattice px-2.5 py-1 font-sans text-[11px] text-graphite transition-colors hover:border-lattice-strong disabled:opacity-40"
            >
              <Check className="h-3 w-3" aria-hidden />
              Mark all read
            </button>
          </header>

          <NotificationList onRowActivated={() => setOpen(false)} />

          <footer className="border-t border-lattice px-4 py-2.5 text-right">
            <Link
              href="/app/notifications"
              onClick={() => setOpen(false)}
              className="font-sans text-[12px] text-crane-deep hover:underline"
            >
              View all →
            </Link>
          </footer>
        </div>
      )}
    </div>
  );
}
