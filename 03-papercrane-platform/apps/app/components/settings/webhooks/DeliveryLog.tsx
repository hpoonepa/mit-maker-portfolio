"use client";

import { ScrollText } from "lucide-react";

interface DeliveryLogProps {
  webhookId: string;
  /** Retained for API compatibility with the post-beta delivery log. */
  limit?: number;
}

/**
 * Delivery log: not available in beta.
 *
 * The delivery history for a webhook is recorded by the delivery worker, and
 * the router has no procedure to read it back yet (`webhooks.deliveries` and
 * `webhooks.retryDelivery` do not exist). Rather than issue calls that fail at
 * runtime, this renders an explicit unreleased state.
 *
 * When the procedures land, restore the virtualized table here: the props
 * (`webhookId`, `limit`) are already the shape it needs.
 */
export function DeliveryLog(_props: DeliveryLogProps) {
  return (
    <section className="overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
        <h2 className="font-display text-[18px] text-ink">Recent deliveries</h2>
        <span className="inline-flex items-center rounded-full border border-lattice bg-paper px-2.5 py-0.5 font-sans text-[12px] text-graphite">
          Not available in beta
        </span>
      </header>

      <div className="px-8 py-12 text-center">
        <div className="mx-auto inline-flex h-12 w-12 items-center justify-center bg-paper">
          <ScrollText className="h-5 w-5 text-graphite" aria-hidden="true" />
        </div>
        <p className="mt-4 mx-auto max-w-md font-sans text-[14px] text-graphite">
          Delivery history isn&apos;t available during the beta. Your webhook is
          live and events are being delivered: you just can&apos;t browse or
          replay past attempts here yet.
        </p>
        <p className="mt-2 mx-auto max-w-md font-sans text-[13px] text-graphite-soft">
          Until then, check the request log on your own endpoint to confirm
          receipt.
        </p>
      </div>
    </section>
  );
}

export default DeliveryLog;
