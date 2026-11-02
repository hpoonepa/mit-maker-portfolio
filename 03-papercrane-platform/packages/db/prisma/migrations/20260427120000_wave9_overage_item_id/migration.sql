-- Paper Crane — Subscription.stripeOverageItemId (Wave 9)
--
-- The seed-meter service emits a Stripe metered usage record on the
-- `seed_overage` subscription item whenever a Pro org with onCap='overage'
-- crosses its soft cap. To call `stripe.subscriptionItems.createUsageRecord`
-- we need the item id, which is populated by the webhook handler on
-- subscription.created / subscription.updated.
--
-- Nullable: existing Free/non-paid orgs do not have a metered item, and
-- legacy Pro subs created before this migration backfill on next webhook.

ALTER TABLE "subscriptions"
  ADD COLUMN "stripe_overage_item_id" TEXT;

-- New audit action for overage usage records, written by seed-meter when a
-- Pro org with onCap='overage' crosses the soft cap and we successfully push
-- a metered record to Stripe.
ALTER TYPE "AuditAction" ADD VALUE IF NOT EXISTS 'billing.overage_recorded';

