import { NotificationPreferences } from "@/components/notifications/NotificationPreferences";

/**
 * `/app/settings/notifications`: toggle prefs (email vs in-app, per
 * category).
 *
 * The `<NotificationPreferences>` client component (Wave 7) owns the tRPC
 * `notifications.preferences.get` / `.update` mutations and the optimistic
 * cache updates. This page just renders the settings-shaped header above
 * it so the section feels native to the rest of the settings tree.
 */
export default function NotificationsSettingsPage() {
  return (
    <div className="space-y-10">
      <header>
        <p className="font-sans text-[12px] text-graphite-soft">
          You
        </p>
        <h1 className="font-display text-display-md text-ink">
          Notifications
        </h1>
        <p className="mt-2 max-w-xl font-sans text-[15px] text-graphite">
          Choose which events reach you in-app and over email. We never send
          marketing: these settings only govern operational events on your
          jobs, billing, webhooks, and invites.
        </p>
      </header>

      <NotificationPreferences />
    </div>
  );
}
