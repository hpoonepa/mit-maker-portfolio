# Stripe Setup (Test Mode)

End-to-end checklist for wiring Paper Crane to Stripe in test mode. Follow
top to bottom; you should be able to complete an upgrade with the demo
card 4242 4242 4242 4242 in under 10 minutes.

## 1. Create products and prices in the Stripe Dashboard

Switch the dashboard to **Test mode** (toggle top-right) before doing
anything else. All resources you create in test mode have ids prefixed
`prod_` / `price_` and are completely isolated from live billing.

Create two products:

| Product       | Pricing                                  | Notes                                                     |
|---------------|------------------------------------------|-----------------------------------------------------------|
| Paper Crane Pro | Recurring, monthly **and** annual       | Two prices on the same product so users can switch cadence in the portal. |
| Seed Pack 10k | One-time payment                          | Becomes the seed top-up SKU.                              |

For each price, copy the `price_...` id — you will paste these into
`.env.local`.

## 2. Local environment variables

Edit `.env.local` (NOT `.env`, which is committed) and set:

```
STRIPE_SECRET_KEY=sk_test_...                  # api only
STRIPE_WEBHOOK_SECRET=whsec_...                # api only — see step 4
STRIPE_PRICE_PRO_MONTHLY=price_...
STRIPE_PRICE_PRO_ANNUAL=price_...
STRIPE_PRICE_PACK_10K=price_...
STRIPE_PRICE_SEAT_ADDON=price_...              # optional, future seat work

# Browser-visible price ids — used by UpgradeModal to render the cadence
# toggle. Safe to expose; price ids are not secret.
NEXT_PUBLIC_STRIPE_PRICE_PRO_MONTHLY=price_...
NEXT_PUBLIC_STRIPE_PRICE_PRO_ANNUAL=price_...
```

Refusal-to-start guarantees:

- `apps/api` will fail health on missing `STRIPE_SECRET_KEY` or
  `STRIPE_WEBHOOK_SECRET`.
- The upgrade button gracefully disables itself if the price env vars are
  missing.

## 3. Run the Stripe CLI locally

The CLI forwards real Stripe webhook events from your test account to your
local API. Without it, `checkout.session.completed` never reaches the
backend and your tier never flips.

```bash
# One-time install
brew install stripe/stripe-cli/stripe

# Login (opens browser, scopes to your test account)
stripe login

# Forward to the local Fastify API. The default listen port is 3001.
stripe listen --forward-to localhost:3001/v1/billing/webhook
```

The CLI prints a `whsec_...` signing secret on first run. Copy it to
`STRIPE_WEBHOOK_SECRET`. This secret is local-only — production uses the
Endpoint signing secret from the Stripe Dashboard.

Keep `stripe listen` running in a separate terminal for the whole session.

## 4. Configure the Customer Portal (one-time)

In the Stripe Dashboard go to **Settings → Billing → Customer portal**
(test mode) and:

1. Activate the portal.
2. Allow plan changes between the Pro monthly and Pro annual prices.
3. Allow customers to cancel subscriptions immediately (we don't enforce
   downgrade gates yet — webhook flips tier on `customer.subscription.deleted`).
4. Save.

The portal URL is generated per-session; nothing else to configure.

## 5. Smoke test the flow

```bash
pnpm dev   # starts api + app
```

In the dashboard:

1. Land on `/app/billing` as a Free user.
2. Click **Upgrade to Pro**.
3. Stripe Checkout opens. Use the demo card:
   - Number: `4242 4242 4242 4242`
   - Expiry: any future date (e.g. `12/34`)
   - CVC: any 3 digits (e.g. `123`)
   - ZIP: any 5 digits (e.g. `12345`)
4. Submit. Stripe redirects to `/app/billing/success?session_id=cs_test_...`.
5. The success page polls `billing.currentSubscription` until the webhook
   flips the org tier to `pro` (typically <3s in test mode), then
   auto-redirects to `/dashboard`.
6. Click **Manage billing** anywhere on the billing page → opens the
   Customer Portal in the same tab. Cancel from there → portal redirects
   back, webhook flips the org back to `free`.

### Helpful test cards

| Scenario              | Card                        |
|-----------------------|-----------------------------|
| Successful payment    | `4242 4242 4242 4242`       |
| Requires 3D Secure    | `4000 0025 0000 3155`       |
| Card declined         | `4000 0000 0000 9995`       |
| Insufficient funds    | `4000 0000 0000 9995`       |

Full list: <https://stripe.com/docs/testing>.

## 6. Top-up packs

The same `/v1/billing/checkout` endpoint accepts a `mode: 'pack'` body
shape. Example tRPC call from the client:

```ts
await trpc.billing.createCheckoutSession.mutate({
  mode: "pack",
  pack: "seeds_10k",
  quantity: 1,
});
```

The webhook handler ignores tier on `mode: payment` events, so a pack
purchase tops up seed credit without touching the org's tier.

## 7. Production checklist (when you flip the live keys)

- Create the same products in Live mode and copy the new `price_...` ids
  into prod env.
- In Stripe Dashboard create a Webhook endpoint pointing at
  `https://<prod-domain>/v1/billing/webhook`. Subscribe to:
  - `checkout.session.completed`
  - `customer.subscription.created`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
  - `invoice.payment_succeeded`
  - `invoice.payment_failed`
- Copy the endpoint signing secret (also `whsec_...`) into prod env.
- Verify the Customer Portal is configured in Live mode (test-mode config
  does not carry over).
- Smoke test with a real card on the deployed staging domain before
  flipping the marketing site.

## Troubleshooting

| Symptom                                        | Likely cause                                                       |
|------------------------------------------------|--------------------------------------------------------------------|
| `400 invalid_signature` on the webhook         | `STRIPE_WEBHOOK_SECRET` does not match the running `stripe listen`. Restart `stripe listen` and re-paste the printed secret. |
| Success page never resolves                    | Webhook isn't reaching the API. Check `stripe listen` output for forwarding errors and confirm the API is on port 3001. |
| `400 missing_price_pro_monthly`                | `STRIPE_PRICE_PRO_MONTHLY` not set in `.env.local`.                |
| `409 no_stripe_customer` from manage billing   | Org has never completed checkout. The portal requires an existing Stripe Customer; subscribe first. |
| Tier doesn't downgrade after cancel            | Customer Portal isn't sending `customer.subscription.deleted`. Make sure the portal config has cancellations enabled. |
