"use client";

import { Check } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useMarkRead,
  useNotifications,
  useUnreadCount,
  type NotificationRow,
} from "@/lib/notifications/hooks";
import { NotificationItem } from "./NotificationItem";

/**
 * Dropdown popover anchored to the bell icon. Shows the most recent ~10
 * notifications and exposes "Mark all read" + "View all" actions.
 *
 * The component is intentionally thin: pagination, filters, and
 * keyboard navigation belong on the full page (`/app/notifications`).
 * Here we just want the operator to glance, dismiss, or jump out.
 */

const DROPDOWN_LIMIT = 10;

type Props = {
  /** Fired after the user clicks a row or "View all" so the bell can collapse. */
  onClose: () => void;
};

export function NotificationDropdown({ onClose }: Props) {
  const query = useNotifications({ limit: DROPDOWN_LIMIT });
  const { markRead, markAllRead, isMarking } = useMarkRead();
  const router = useRouter();
  const unread = useUnreadCount();

  const pages =
    (query.data as { pages?: Array<{ items: NotificationRow[] }> } | undefined)
      ?.pages ?? [];
  const rows = pages.flatMap((p) => p.items).slice(0, DROPDOWN_LIMIT);

  const handleOpen = (row: NotificationRow) => {
    if (row.readAt === null) {
      markRead(row.id).catch(() => {});
    }
    if (row.actionUrl) router.push(row.actionUrl);
    onClose();
  };

  const handleDismiss = (id: string) => {
    markRead(id).catch(() => {});
  };

  return (
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

      <div className="max-h-[420px] overflow-y-auto px-2 pb-2 pt-2">
        {query.isLoading ? (
          <div className="px-3 py-6 text-center font-sans text-[12px] text-graphite-soft">
            Loading notifications…
          </div>
        ) : rows.length === 0 ? (
          <div className="px-3 py-10 text-center">
            <div className="font-sans text-[13px] text-ink">
              You&apos;re all caught up.
            </div>
            <div className="mt-1 font-sans text-[12px] text-graphite-soft">
              New notifications will appear here.
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-1">
            {rows.map((row) => (
              <NotificationItem
                key={row.id}
                row={row}
                onOpen={handleOpen}
                onDismiss={handleDismiss}
              />
            ))}
          </div>
        )}
      </div>

      <footer className="border-t border-lattice px-4 py-2.5 text-right">
        <Link
          href="/app/notifications"
          onClick={onClose}
          className="font-sans text-[12px] text-crane-deep hover:underline"
        >
          View all →
        </Link>
      </footer>
    </div>
  );
}
