import type Stripe from "stripe";
import type { SubscriptionStatus as PrismaSubscriptionStatus } from "@papercrane/db";
import type { WebhookContext } from "../webhooks.js";

/**
 * Handle invoice.paid and invoice.payment_failed.
 *
 * Stripe drives the retry schedule ("Smart Retries" in the Dashboard). Our
 * job is just to mirror the dunning state onto our Subscription row so the
 * tier-enforcement gateway can flag the org in-app, and so ops can query
 * past-due orgs from our DB without hitting Stripe.
 *
 * On success (`invoice.paid`):   status → active
 * On failure (`payment_failed`): status → past_due
 *
 * The customer.subscription.updated event will also arrive and re-set status
 * via the subscription handler; updates converge either way. We write here
 * primarily because payment_failed sometimes lands first, and so that
 * `invoice.paid` for prorations (mid-cycle upgrades) can clear transient
 * past_due without waiting for the subscription event.
 *
 * Final downgrade to Free on persistent failure is driven by Stripe itself:
 * after Smart Retries exhaust it emits customer.subscription.deleted, which
 * our subscription handler downgrades to Free.
 */

export async function handleInvoiceEvent(
  event: Stripe.Event,
  ctx: WebhookContext,
): Promise<void> {
  const invoice = event.data.object as Stripe.Invoice;
  const subscriptionId =
    typeof invoice.subscription === "string"
      ? invoice.subscription
      : invoice.subscription?.id;

  if (!subscriptionId) {
    // One-off invoices (Frontier manual flow, seed-pack Checkout) don't
    // carry a subscription id — they're not dunning-relevant here.
    ctx.logger.debug(
      { eventId: event.id, eventType: event.type, invoiceId: invoice.id },
      "billing.invoice: non-subscription invoice, skipping",
    );
    return;
  }

  const targetStatus: PrismaSubscriptionStatus =
    event.type === "invoice.paid" ? "active" : "past_due";

  const updated = await ctx.prisma.subscription.updateMany({
    where: { stripeSubscriptionId: subscriptionId },
    data: { status: targetStatus },
  });

  ctx.logger.info(
    {
      eventId: event.id,
      eventType: event.type,
      invoiceId: invoice.id,
      subscriptionId,
      targetStatus,
      rowsUpdated: updated.count,
    },
    event.type === "invoice.paid"
      ? "billing.invoice: marked active"
      : "billing.invoice: marked past_due (dunning)",
  );
}
