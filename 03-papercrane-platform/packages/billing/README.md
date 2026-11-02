# @papercrane/billing

Stripe integration — Checkout, Customer Portal, and webhook dispatch.

Pure domain package: no Fastify, no HTTP. The API service
(`apps/api/src/routes/rest/billing.ts`) owns the HTTP surface and hands raw
request bytes into these functions.

## Layout

```
src/
  client.ts              Stripe client factory (pinned apiVersion)
  checkout.ts            createCheckoutSession()
  portal.ts              createPortalSession()
  verifySignature.ts     verifyAndParseEvent()
  webhooks.ts            handleWebhookEvent() + WebhookContext
  tiers.ts               price-id → tier/flag mapping
  handlers/
    subscription.ts      customer.subscription.{created,updated,deleted}
    invoice.ts           invoice.{paid,payment_failed}
    checkout.ts          checkout.session.completed
tests/
  webhooks.test.ts
  checkout.test.ts
  tiers.test.ts
```

## Event flow

1. HTTP POST `/v1/billing/webhook` arrives with a raw JSON body and
   `Stripe-Signature` header.
2. Route calls `verifyAndParseEvent({ rawBody, signature }, { stripe, webhookSecret })`.
3. Route calls `handleWebhookEvent(event, ctx)`:
   - Redis `SET NX EX 7d` on `stripe:webhook:<event.id>` — skip if duplicate.
   - Switch on `event.type`, dispatch to the matching handler in `handlers/`.
4. Handler mutates DB (Subscription / Organization / FeatureFlag). All writes
   are idempotent upserts keyed on stable Stripe ids.
5. Route returns 200.

## Env vars consumed

| Var | Required | Purpose |
|---|---|---|
| `STRIPE_SECRET_KEY` | yes | `createStripeClient` |
| `STRIPE_WEBHOOK_SECRET` | yes | `verifyAndParseEvent` |
| `STRIPE_PRICE_PRO_MONTHLY` | yes | Tier mapping |
| `STRIPE_PRICE_PRO_ANNUAL` | yes | Tier mapping |
| `STRIPE_PRICE_SEAT_ADDON` | no | Acknowledged as non-tier |
| `STRIPE_PRICE_PACK_10K` | no | Acknowledged as non-tier |

## Design notes

- `tiers.ts` is the single source of truth for which price → which tier. If
  `packages/db/prisma/schema.prisma` changes the `FeatureFlag` defaults,
  update `freeTierFlags` here in the same PR.
- Subscriptions can have multiple line items (Pro base + seat add-on). The
  dispatcher picks the Pro-tier item as the driving price; seat add-ons and
  seed packs never mutate the org's tier.
- Idempotency is two layers deep: Redis dedup + DB upserts. Redis handles the
  common case (at-least-once retries); DB upserts cover the Redis-down case.
- Signature verification is the first thing the route does — a failure
  returns 400 before any handler runs, and the Redis key is never written.
