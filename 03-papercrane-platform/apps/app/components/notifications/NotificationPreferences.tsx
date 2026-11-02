"use client";

import { trpc } from "@/lib/trpc/client";
import type { NotificationCategory } from "@/lib/notifications/hooks";

/**
 * Per-user, per-category notification preferences. Embedded into the
 * settings page (see `apps/app/app/(dashboard)/settings/page.tsx`).
 *
 * Each row is (category × channel). We render two channel toggles per
 * category: "in-app" and "email". The mutation is fire-and-forget from
 * the UI's perspective; we optimistically update the cache on click,
 * and the router re-confirms.
 */

type ChannelKey = "inApp" | "email";

type CategoryRowMeta = {
  key: NotificationCategory;
  label: string;
  description: string;
};

const CATEGORIES: CategoryRowMeta[] = [
  {
    key: "job",
    label: "Jobs",
    description: "Job completed, failed, or cancelled.",
  },
  {
    key: "billing",
    label: "Billing",
    description: "Seed-cap warnings, invoice events, trial reminders.",
  },
  {
    key: "webhook",
    label: "Webhooks",
    description: "Webhook delivery failures for subscriptions you own.",
  },
  {
    key: "invite",
    label: "Invites",
    description: "Workspace invites received.",
  },
  {
    key: "system",
    label: "System",
    description: "Paper Crane announcements and maintenance notices.",
  },
];

function Toggle({
  checked,
  disabled,
  onChange,
  label,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
        checked ? "bg-crane-deep" : "bg-lattice"
      } ${disabled ? "opacity-50" : ""}`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-paper transition-transform ${
          checked ? "translate-x-4" : "translate-x-0.5"
        }`}
      />
    </button>
  );
}

export function NotificationPreferences() {
  const q = trpc.notifications.preferences.get.useQuery();
  const update = trpc.notifications.preferences.update.useMutation({
    onSuccess: () => {
      q.refetch?.();
    },
  });

  // Shape returned by the router: `{ prefs: { category: { inApp, email } } }`.
  const prefs = (q.data as
    | { prefs: Record<NotificationCategory, Record<ChannelKey, boolean>> }
    | undefined
  )?.prefs;

  const enabled = (cat: NotificationCategory, ch: ChannelKey): boolean => {
    return prefs ? prefs[cat]?.[ch] ?? false : false;
  };

  const setEnabled = (
    cat: NotificationCategory,
    ch: ChannelKey,
    next: boolean,
  ) => {
    update.mutate({
      category: cat,
      channel: ch === "inApp" ? "in_app" : "email",
      enabled: next,
    });
  };

  return (
    <section className="rounded-lg border border-lattice bg-paper">
      <header className="border-b border-lattice px-4 py-3">
        <div className="font-sans text-[13px] font-medium text-ink">
          Notification preferences
        </div>
        <div className="mt-0.5 font-sans text-[12px] text-graphite-soft">
          Choose which categories reach you in-app and over email.
        </div>
      </header>

      <div className="divide-y divide-lattice">
        {CATEGORIES.map((cat) => (
          <div
            key={cat.key}
            className="flex items-start justify-between gap-4 px-4 py-3"
          >
            <div className="min-w-0 flex-1">
              <div className="font-sans text-[13px] text-ink">{cat.label}</div>
              <p className="mt-0.5 font-sans text-[12px] text-graphite-soft">
                {cat.description}
              </p>
            </div>
            <div className="flex items-center gap-4 pt-0.5">
              <label className="flex items-center gap-2 font-sans text-[12px] text-graphite">
                <span>In-app</span>
                <Toggle
                  label={`${cat.label} in-app`}
                  checked={enabled(cat.key, "inApp")}
                  disabled={q.isLoading || update.isPending}
                  onChange={(n) => setEnabled(cat.key, "inApp", n)}
                />
              </label>
              <label className="flex items-center gap-2 font-sans text-[12px] text-graphite">
                <span>Email</span>
                <Toggle
                  label={`${cat.label} email`}
                  checked={enabled(cat.key, "email")}
                  disabled={q.isLoading || update.isPending}
                  onChange={(n) => setEnabled(cat.key, "email", n)}
                />
              </label>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
