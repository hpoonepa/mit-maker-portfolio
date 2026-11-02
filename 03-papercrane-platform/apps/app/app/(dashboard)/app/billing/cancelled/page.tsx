/**
 * `/app/billing/cancelled`: gentle landing when the user backs out of
 * Stripe Checkout. No tier change happens; we just acknowledge and hand
 * them back to the billing page so they can try a different cadence or
 * cancel for real.
 */

export const dynamic = "force-dynamic";

export default function CheckoutCancelledPage() {
  return (
    <div className="mx-auto max-w-xl py-16">
      <div className="bg-paper p-10 text-center">
        <p className="font-sans text-[12px] text-graphite-soft">
          Checkout cancelled
        </p>
        <h1 className="font-display text-display-md text-ink">
          No problem.
        </h1>
        <p className="mt-3 font-sans text-[14px] text-graphite">
          Your card was not charged and your workspace is unchanged. Whenever
          you&rsquo;re ready, the upgrade is one click away.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <a
            href="/app/billing"
            className="inline-flex items-center gap-2 rounded-full bg-ink px-5 py-2.5 font-sans text-[13px] text-paper hover:bg-ink/90"
          >
            Back to billing
          </a>
          <a
            href="/dashboard"
            className="inline-flex items-center gap-2 rounded-full border border-lattice px-5 py-2.5 font-sans text-[13px] text-ink hover:bg-paper-fold/50"
          >
            Go to dashboard
          </a>
        </div>
      </div>
    </div>
  );
}
