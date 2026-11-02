import { WebhookList } from "@/components/settings/webhooks/WebhookList";
import { WebhookSignatureExample } from "@/components/settings/WebhookSignatureExample";

/**
 * `/app/settings/webhooks`: list, create, test-fire, and recent deliveries.
 *
 * The `<WebhookList>` client component (Wave 7) owns:
 *   - tRPC `webhooks.list` query + create form + empty-state CTA
 *   - per-row test-fire button (POSTs sample payload, surfaces response)
 *   - drill-in to a per-webhook detail page with delivery history
 *
 * This page also renders the language-tabbed signature verification snippet
 * so anyone landing here from the docs sees both the management list AND
 * the canonical "verify the HMAC" recipe in one place.
 */
export default function WebhooksSettingsPage() {
  return (
    <div className="space-y-10">
      <WebhookList />
      <WebhookSignatureExample />
    </div>
  );
}
