"use client";

import type {
  RealtimeChannel,
  RealtimePostgresChangesPayload,
  SupabaseClient,
} from "@supabase/supabase-js";

import { createSupabaseBrowserClient } from "@/lib/supabase/client";

export type PgChangeEvent = "INSERT" | "UPDATE" | "DELETE" | "*";

// Supabase's RealtimePostgresChangesPayload requires this exact open-row constraint.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export interface PgChangeSubscription<T extends { [key: string]: any }> {
  /** Postgres table name (snake_case, public schema). */
  table: string;
  /** Which row mutations to listen for. Defaults to "*". */
  event?: PgChangeEvent;
  /**
   * Server-side filter, e.g. `org_id=eq.${orgId}`. Realtime applies this on
   * the broker before delivery, so it must be a column the user is allowed
   * to read under RLS: otherwise the row is dropped silently.
   */
  filter?: string;
  /** Channel name; should be unique per (table, scope) pair. */
  channelName: string;
  onChange: (payload: RealtimePostgresChangesPayload<T>) => void;
  onError?: (error: Error) => void;
}

/**
 * Thin wrapper around Supabase Realtime's `postgres_changes` channel API.
 *
 * Returns an unsubscribe function. Always call it on unmount: leaked
 * channels keep the websocket open and burn against the project's
 * concurrent-connection quota.
 *
 * RLS is enforced on the database, so even if a caller passes a wrong
 * filter they cannot receive rows from other orgs.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function subscribeToPgChanges<T extends { [key: string]: any }>(
  sub: PgChangeSubscription<T>,
  client?: SupabaseClient
): () => void {
  const supabase = client ?? createSupabaseBrowserClient();
  const channel: RealtimeChannel = supabase.channel(sub.channelName);

  // Cast: supabase-js types `postgres_changes` config loosely.
  (channel.on as unknown as (
    type: string,
    config: Record<string, unknown>,
    cb: (payload: RealtimePostgresChangesPayload<T>) => void,
  ) => RealtimeChannel)(
    "postgres_changes",
    {
      event: sub.event ?? "*",
      schema: "public",
      table: sub.table,
      ...(sub.filter ? { filter: sub.filter } : {}),
    },
    (payload: RealtimePostgresChangesPayload<T>) => {
      try {
        sub.onChange(payload);
      } catch (err) {
        sub.onError?.(err instanceof Error ? err : new Error(String(err)));
      }
    },
  )
    .subscribe((status, err) => {
      if (status === "CHANNEL_ERROR" || status === "TIMED_OUT") {
        sub.onError?.(err ?? new Error(`Realtime channel ${status}`));
      }
    });

  return () => {
    void supabase.removeChannel(channel);
  };
}
