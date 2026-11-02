"use client";

import { useEffect, useState } from "react";

import { subscribeToPgChanges } from "@/lib/realtime/supabase-rt";

export interface NotificationRow {
  id: string;
  org_id: string;
  job_id: string | null;
  user_id: string | null;
  kind: string;
  title: string;
  body: string | null;
  read_at: string | null;
  created_at: string;
}

export interface UseNotificationRealtimeOptions {
  /**
   * Called for every newly inserted notification. Typical use: pop a toast
   * ("Job 'GLP-1R bind 1' succeeded: 12 new designs"). Keep it cheap;
   * heavy work belongs in a queue, not here.
   */
  onNotification?: (n: NotificationRow) => void;
}

export interface UseNotificationRealtimeResult {
  notifications: NotificationRow[];
  unreadCount: number;
  error: Error | null;
}

/**
 * Global notification stream for the current org. RLS scopes the publication
 * by org_id: we don't pass a filter here because users may belong to
 * multiple orgs and the row-level policy already restricts the result set.
 *
 * Keeps the most recent 50 notifications in memory; older ones should be
 * fetched via the notifications inbox query.
 */
export function useNotificationRealtime(
  opts: UseNotificationRealtimeOptions = {}
): UseNotificationRealtimeResult {
  const [notifications, setNotifications] = useState<NotificationRow[]>([]);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    const unsubscribe = subscribeToPgChanges<NotificationRow>({
      channelName: "rt:notifications:self",
      table: "notifications",
      event: "INSERT",
      onChange: (payload) => {
        const row = payload.new as Partial<NotificationRow> | undefined;
        if (!row?.id) return;
        const full = row as NotificationRow;
        setNotifications((prev) => {
          if (prev.some((n) => n.id === full.id)) return prev;
          return [full, ...prev].slice(0, 50);
        });
        opts.onNotification?.(full);
      },
      onError: (err) => setError(err),
    });

    return unsubscribe;
    // onNotification is intentionally excluded: callers should memoize it
    // or accept that we capture the first instance for the lifetime of the
    // subscription. Re-subscribing on every render would thrash the channel.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const unreadCount = notifications.filter((n) => !n.read_at).length;

  return { notifications, unreadCount, error };
}
