"use client";

import { useEffect, useRef, useState, type KeyboardEvent as ReactKbd } from "react";
import { useRouter } from "next/navigation";
import {
  useMarkRead,
  useNotifications,
  type NotificationRow,
} from "@/lib/notifications/hooks";
import { NotificationItem } from "./NotificationItem";

/**
 * Scrolling list inside the popover.
 *
 * "Virtualization" is implemented as a windowed slice: we keep at most
 * 50 rows in the DOM at a time and rely on an IntersectionObserver on a
 * sentinel at the bottom to pull more pages. This avoids taking on a
 * new dep (no `react-window`) while still keeping the DOM small for
 * long histories.
 *
 * Keyboard:
 *   - ArrowDown / ArrowUp move focus across items
 *   - Enter activates (handled by the <button> inside each item)
 *   - Escape is handled by the parent popover
 */

type Props = {
  unreadOnly?: boolean;
  /** Called after the user activates a row; popover uses this to close. */
  onRowActivated?: () => void;
};

const PAGE_WINDOW = 50;

export function NotificationList({ unreadOnly, onRowActivated }: Props) {
  const query = useNotifications({ unreadOnly });
  const { markRead } = useMarkRead();
  const router = useRouter();
  const sentinelRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [focusIndex, setFocusIndex] = useState(0);

  const pages = (query.data as { pages?: Array<{ items: NotificationRow[] }> } | undefined)?.pages ?? [];
  const rowsAll = pages.flatMap((p) => p.items);
  const rows = rowsAll.slice(-PAGE_WINDOW);

  // Infinite-scroll trigger.
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && query.hasNextPage && !query.isFetchingNextPage) {
            query.fetchNextPage();
          }
        }
      },
      { root: el.parentElement, rootMargin: "100px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [query]);

  const handleOpen = async (row: NotificationRow) => {
    if (row.readAt === null) {
      // Fire-and-forget: the UI has already optimistically marked it via
      // the cache update in useMarkRead's onSuccess.
      markRead(row.id).catch(() => {
        // Silently swallow; cache invalidation will surface the real state.
      });
    }
    if (row.actionUrl) {
      router.push(row.actionUrl);
    }
    onRowActivated?.();
  };

  const handleDismiss = (id: string) => {
    markRead(id).catch(() => {});
  };

  const onKeyDown = (e: ReactKbd<HTMLDivElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setFocusIndex((i) => Math.min(rows.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setFocusIndex((i) => Math.max(0, i - 1));
    }
  };

  // Move DOM focus to the currently-selected row.
  useEffect(() => {
    const root = listRef.current;
    if (!root || rows.length === 0) return;
    const buttons = root.querySelectorAll<HTMLButtonElement>(
      "button[data-notification-id]",
    );
    const target = buttons[focusIndex];
    if (target && document.activeElement !== target) target.focus();
  }, [focusIndex, rows.length]);

  if (query.isLoading) {
    return (
      <div className="px-3 py-6 text-center font-sans text-[12px] text-graphite-soft">
        Loading notifications…
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="px-3 py-12 text-center">
        <div className="font-serif text-[15px] italic text-ink">
          Nothing folded for your attention.
        </div>
        <div className="mt-1 font-sans text-[12px] r text-graphite-soft">
          inbox · clear
        </div>
      </div>
    );
  }

  return (
    <div
      ref={listRef}
      role="list"
      tabIndex={-1}
      onKeyDown={onKeyDown}
      className="flex max-h-96 flex-col overflow-y-auto outline-none"
    >
      {rows.map((row) => (
        <NotificationItem
          key={row.id}
          row={row}
          onOpen={handleOpen}
          onDismiss={handleDismiss}
        />
      ))}
      <div ref={sentinelRef} aria-hidden className="h-2 w-full" />
      {query.isFetchingNextPage && (
        <div className="py-2 text-center font-sans text-[11px] text-graphite-soft">
          Loading more…
        </div>
      )}
    </div>
  );
}
