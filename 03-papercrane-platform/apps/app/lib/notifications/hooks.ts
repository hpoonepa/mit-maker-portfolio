"use client";

import { useCallback } from "react";
import { trpc } from "@/lib/trpc/client";

/**
 * Client-side hooks + helpers for the notification center.
 *
 * Layering
 * --------
 * Pure helpers (`computeUnreadCount`, `formatUnreadBadge`, `categoryIcon`)
 * are plain functions so they can be unit-tested without the React tree.
 * The React hooks wrap `trpc.notifications.*` endpoints + React Query's
 * cache helpers.
 *
 * Server-side authorization and RLS live in the tRPC router; these hooks
 * trust whatever the router returns (the caller's own rows only).
 */

export type NotificationCategory =
  | "job"
  | "billing"
  | "webhook"
  | "invite"
  | "system";

export type NotificationRow = {
  id: string;
  category: NotificationCategory;
  title: string;
  description: string | null;
  readAt: string | null;
  actionUrl: string | null;
  metadata: Record<string, unknown> | null;
  createdAt: string;
};

// ─── Pure helpers (unit-tested) ─────────────────────────────────────────────

export function computeUnreadCount(
  rows: Array<Pick<NotificationRow, "readAt">>,
): number {
  let n = 0;
  for (const r of rows) if (r.readAt === null) n += 1;
  return n;
}

/** Format an unread count for a TopBar badge. Caps at "99+". */
export function formatUnreadBadge(count: number): string {
  if (count <= 0) return "";
  if (count > 99) return "99+";
  return String(count);
}

/**
 * Map a category to a lucide-react icon name. The caller resolves the
 * component: keeping this as a string constant means it's testable
 * without rendering and lets the caller tree-shake icon imports.
 */
export function categoryIcon(category: NotificationCategory): string {
  switch (category) {
    case "job":
      return "Cpu";
    case "billing":
      return "CreditCard";
    case "webhook":
      return "PlugZap";
    case "invite":
      return "UserPlus";
    case "system":
    default:
      return "Bell";
  }
}

// ─── React hooks ────────────────────────────────────────────────────────────

/**
 * Paginated list of the caller's notifications. Uses `useInfiniteQuery`
 * so the full-page `/app/notifications` view can lazily load history.
 */
export function useNotifications(opts?: {
  unreadOnly?: boolean;
  limit?: number;
}) {
  const unreadOnly = opts?.unreadOnly ?? false;
  const limit = opts?.limit ?? 25;
  return trpc.notifications.list.useInfiniteQuery(
    { limit, unreadOnly },
    {
      getNextPageParam: (last: { nextCursor?: string }) => last.nextCursor,
    },
  );
}

/**
 * Live unread count. Derived from the first page of the list query so we
 * don't issue a second round-trip; the realtime subscription (see
 * `./realtime.ts`) invalidates the list cache on INSERT/UPDATE, which
 * transparently refreshes this value.
 */
export function useUnreadCount(): number {
  const q = trpc.notifications.list.useQuery({ limit: 100, unreadOnly: true });
  const rows = (q.data?.items ?? []) as Array<Pick<NotificationRow, "readAt">>;
  return computeUnreadCount(rows);
}

/**
 * Returns `markRead(id)` and `markAllRead()` handlers wired to the tRPC
 * mutations. Both invalidate the list query on success so UI re-renders
 * without a reload.
 */
export function useMarkRead() {
  const utils = trpc.useUtils();
  const markOne = trpc.notifications.markRead.useMutation({
    onSuccess: () => {
      utils.notifications.list.invalidate();
    },
  });
  const markAll = trpc.notifications.markAllRead.useMutation({
    onSuccess: () => {
      utils.notifications.list.invalidate();
    },
  });

  const markRead = useCallback(
    (id: string) => markOne.mutateAsync({ id }),
    [markOne],
  );
  const markAllRead = useCallback(() => markAll.mutateAsync(), [markAll]);

  return {
    markRead,
    markAllRead,
    isMarking: markOne.isPending || markAll.isPending,
  };
}
