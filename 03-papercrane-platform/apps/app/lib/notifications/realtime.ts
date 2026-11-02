"use client";

import { useEffect, useRef } from "react";
import { createSupabaseBrowserClient } from "@/lib/supabase/client";
import { trpc } from "@/lib/trpc/client";

/**
 * Subscribe to Supabase realtime events on the `notifications` table and
 * invalidate the tRPC cache whenever something lands for the current user.
 *
 * This hook is a no-op if either the Supabase env vars are missing or the
 * tRPC utils tree does not yet expose the notifications router (e.g. in
 * tests). That lets the bell icon component mount unconditionally without
 * conditionally wiring realtime.
 *
 * Filter: `user_id=eq.<uid>`. We pass the signed-in user's id in (resolved
 * at the layout/server level), and the browser client enforces RLS on the
 * subscription too: a malicious client cannot subscribe to another user's
 * notifications even if they spoof the filter.
 */
export function useNotificationsRealtime(userId: string | null) {
  const utils = trpc.useUtils();
  // Stable ref for the invalidator. `utils` is recreated on every render of
  // the tRPC provider, so depending on it directly would tear down and
  // rebuild the websocket channel on each parent re-render.
  const invalidate = () => utils.notifications.list.invalidate();
  const invalidateRef = useRef(invalidate);
  invalidateRef.current = invalidate;

  useEffect(() => {
    if (!userId) return;
    let supabase: ReturnType<typeof createSupabaseBrowserClient>;
    try {
      supabase = createSupabaseBrowserClient();
    } catch {
      // Env not configured (CI / local without Supabase): skip silently.
      return;
    }

    const channel = supabase
      .channel(`rt:notifications:user:${userId}`)
      .on(
        // `postgres_changes` event name is stable across @supabase/supabase-js 2.x.
        // Loose-typed to avoid pulling the full realtime-js type surface in here.
        "postgres_changes" as never,
        {
          event: "*",
          schema: "public",
          table: "notifications",
          filter: `user_id=eq.${userId}`,
        } as never,
        () => {
          // Any change to this user's notifications → refetch the list.
          invalidateRef.current();
        },
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
    // Intentionally only depend on `userId`; `invalidateRef` is stable and
    // reading `utils` directly would churn the channel on parent re-renders.

  }, [userId]);
}
