import { WebhookDetail } from "@/components/settings/webhooks/WebhookDetail";

/**
 * `/app/settings/webhooks/[id]`: detail + delivery history.
 *
 * Server shell; `<WebhookDetail />` handles fetches, mutations, and the
 * virtualized delivery log.
 */
export default async function WebhookDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <WebhookDetail webhookId={id} />;
}
