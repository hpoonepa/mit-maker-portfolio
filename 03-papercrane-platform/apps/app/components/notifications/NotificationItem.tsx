"use client";

import { Bell, CreditCard, Cpu, PlugZap, UserPlus, X } from "lucide-react";
import type { MouseEvent as ReactMouseEvent } from "react";
import type { NotificationRow } from "@/lib/notifications/hooks";

/**
 * A single notification row.
 *
 * Interaction contract:
 *   - clicking the body  → `onOpen(row)`: caller marks it read + navigates
 *                          to `action_url` if present.
 *   - clicking the ×     → `onDismiss(row.id)`: caller marks it read only.
 *   - keyboard focus     → body is a <button>, so Enter/Space activate.
 */

type Props = {
  row: NotificationRow;
  onOpen: (row: NotificationRow) => void;
  onDismiss: (id: string) => void;
};

const CATEGORY_ICON = {
  job: Cpu,
  billing: CreditCard,
  webhook: PlugZap,
  invite: UserPlus,
  system: Bell,
} as const;

function formatRelative(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const sec = Math.round(diffMs / 1000);
  if (sec < 60) return `${Math.max(0, sec)}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  return `${day}d ago`;
}

export function NotificationItem({ row, onOpen, onDismiss }: Props) {
  const Icon = CATEGORY_ICON[row.category] ?? Bell;
  const unread = row.readAt === null;

  const handleDismiss = (e: ReactMouseEvent) => {
    e.stopPropagation();
    onDismiss(row.id);
  };

  return (
    <button
      type="button"
      onClick={() => onOpen(row)}
      data-notification-id={row.id}
      data-unread={unread}
      className="group flex w-full items-center gap-3 border-b border-lattice bg-paper px-3 py-2 text-left transition-colors last:border-b-0 hover:bg-paper-fold"
    >
      <span
        aria-label={unread ? "Unread" : undefined}
        className={`shrink-0 inline-block h-1.5 w-1.5 rounded-full ${
          unread ? "bg-crane-deep" : "bg-transparent"
        }`}
      />
      <div className="shrink-0 text-graphite-soft">
        <Icon className="h-3.5 w-3.5" aria-hidden />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span
            className={`truncate font-sans text-[13px] ${
              unread ? "font-medium text-ink" : "text-graphite"
            }`}
          >
            {row.title}
          </span>
          {row.description && (
            <span className="truncate font-sans text-[12px] text-graphite-soft">
              {row.description}
            </span>
          )}
        </div>
      </div>
      <div className="shrink-0 font-sans text-[12px] r tabular-nums text-graphite-soft">
        {formatRelative(row.createdAt)}
      </div>
      <span
        role="button"
        tabIndex={0}
        aria-label="Dismiss"
        onClick={handleDismiss}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            e.stopPropagation();
            onDismiss(row.id);
          }
        }}
        className="shrink-0 rounded-md p-1 text-graphite-soft opacity-0 transition-opacity hover:bg-paper-fold hover:text-ink group-hover:opacity-100 focus:opacity-100"
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </span>
    </button>
  );
}
