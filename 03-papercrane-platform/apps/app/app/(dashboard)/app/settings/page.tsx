import {
  Bell,
  CreditCard,
  KeyRound,
  Plug,
  User,
  Users,
  Webhook as WebhookIcon,
} from "lucide-react";
import { SectionCard } from "@/components/settings/SectionCard";

/**
 * `/app/settings`: settings landing page.
 *
 * Pure server component. Each tile is a `<SectionCard>` linking into the
 * sub-route that owns its tRPC state. The landing intentionally has no
 * data fetches of its own so navigation feels instant.
 *
 * Section ordering follows the principle of "self → integrations → org":
 *   1. Profile         : your identity
 *   2. Notifications   : your inbox
 *   3. API keys        : machine identities you own
 *   4. Webhooks        : outbound integrations
 *   5. Team            : workspace members
 *   6. Billing         : workspace finances
 */
export default function SettingsLandingPage() {
  return (
    <div className="space-y-10">
      <header>
        <h1 className="font-display text-display-md text-ink">Settings</h1>
      </header>

      <section className="grid grid-cols-1 gap-x-12 gap-y-5 md:grid-cols-2">
        <SectionCard
          href="/app/settings/profile"
          icon={<User className="h-4 w-4" />}
          title="Profile"
          description="Your name, email, and avatar: visible to teammates."
        />
        <SectionCard
          href="/app/settings/notifications"
          icon={<Bell className="h-4 w-4" />}
          title="Notifications"
          description="Choose which events reach you in-app and over email."
        />
        <SectionCard
          href="/app/settings/api-keys"
          icon={<KeyRound className="h-4 w-4" />}
          title="API keys"
          description="Issue, rotate, and revoke keys for scripts and CI."
        />
        <SectionCard
          href="/app/settings/webhooks"
          icon={<WebhookIcon className="h-4 w-4" />}
          title="Webhooks"
          description="Stream signed events to your services as jobs run."
        />
        <SectionCard
          href="/app/settings/integrations"
          icon={<Plug className="h-4 w-4" />}
          title="Integrations"
          description="Connect Modal compute plus Slack and Discord updates."
        />
        <SectionCard
          href="/app/settings/team"
          icon={<Users className="h-4 w-4" />}
          title="Team"
          description="Invite teammates and manage roles for this workspace."
        />
        <SectionCard
          href="/app/settings/billing"
          icon={<CreditCard className="h-4 w-4" />}
          title="Billing"
          description="Plan, seats, invoices, and the seed-budget meter."
        />
      </section>

    </div>
  );
}
