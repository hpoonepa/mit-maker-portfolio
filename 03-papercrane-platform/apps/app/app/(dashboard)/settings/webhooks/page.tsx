import { IntegrationsPanel } from "@/components/settings/webhooks/IntegrationsPanel";
import { WebhookList } from "@/components/settings/webhooks/WebhookList";

/**
 * `/settings/webhooks`: Wave-D consolidated webhooks + chat-integrations
 * surface.
 *
 * Two stacked sections:
 *   1. Outbound HMAC webhooks (existing `<WebhookList>`: own URL receiver).
 *   2. Slack / Discord chat integrations (`<IntegrationsPanel>`: wires
 *      `integrations.list/connect/updateChannel/disconnect`).
 *
 * Both share the same settings shell typography to match `/settings/keys`.
 */
export default function WebhooksSettingsPage() {
  return (
    <div className="space-y-10">
      <header className="border-b border-graphite-soft/15 pb-5">
        <p className="font-sans text-[12px] text-graphite-soft">
          Developers
        </p>
        <h1 className=".5 font-sans text-[22px] font-medium tracking-tight text-ink">
          Webhooks
        </h1>
        <p className="mt-1.5 max-w-xl font-sans text-[13.5px] leading-relaxed text-graphite">
          Receive signed JSON events on your own endpoints, or forward them
          into a Slack or Discord channel. Each row keeps its own event filter
          and mute state. Delivery logs and test-fires arrive after the beta.
        </p>
      </header>

      <WebhookList />
      <IntegrationsPanel />
    </div>
  );
}
