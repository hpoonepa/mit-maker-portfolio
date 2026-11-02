"use client";

import { Check } from "lucide-react";
import { useState } from "react";
import { NotificationList } from "@/components/notifications/NotificationList";
import { useMarkRead, useUnreadCount } from "@/lib/notifications/hooks";

/**
 * Full-page notification history at `/app/notifications`.
 *
 * Differs from the bell dropdown in two ways:
 *   - no width cap: fills the dashboard's 6xl content column
 *   - filter chips toggle between "All" and "Unread only"
 *
 * Client component because filter state is local and the underlying
 * tRPC query already runs through React Query on the client.
 */
export default function NotificationsPage() {
  const [unreadOnly, setUnreadOnly] = useState(false);
  const unread = useUnreadCount();
  const { markAllRead, isMarking } = useMarkRead();

  return (
    <div className="flex flex-col gap-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="font-serif text-2xl text-ink">Notifications</h1>
          <p className="mt-1 font-sans text-[13px] text-graphite-soft">
            Job results, billing alerts, and workspace activity.
          </p>
        </div>
        <button
          type="button"
          onClick={() => markAllRead().catch(() => {})}
          disabled={isMarking || unread === 0}
          className="inline-flex items-center gap-2 rounded-full border border-lattice bg-paper px-3 py-1.5 font-sans text-[12px] text-graphite transition-colors hover:border-lattice-strong disabled:opacity-40"
        >
          <Check className="h-3.5 w-3.5" aria-hidden />
          Mark all as read
        </button>
      </header>

      <div className="flex gap-2">
        <FilterChip
          active={!unreadOnly}
          onClick={() => setUnreadOnly(false)}
          label="All"
        />
        <FilterChip
          active={unreadOnly}
          onClick={() => setUnreadOnly(true)}
          label={`Unread${unread > 0 ? ` (${unread})` : ""}`}
        />
      </div>

      <div className="rounded-lg border border-lattice bg-paper">
        <NotificationList unreadOnly={unreadOnly} />
      </div>
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full border px-3 py-1 font-sans text-[12px] transition-colors ${
        active
          ? "border-ink bg-ink text-paper"
          : "border-lattice bg-paper text-graphite hover:border-lattice-strong"
      }`}
    >
      {label}
    </button>
  );
}
