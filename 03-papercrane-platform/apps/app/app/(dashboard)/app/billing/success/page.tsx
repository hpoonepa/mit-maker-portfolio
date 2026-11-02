"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2, Loader2 } from "lucide-react";
import { trpc } from "@/lib/trpc/client";

/**
 * `/app/billing/success`: landing page after a successful Stripe Checkout.
 *
 * Stripe redirects here with `?session_id=cs_test_...`. We don't trust the
 * session_id alone (the webhook is the source of truth for the org tier),
 * so we poll `billing.currentSubscription` until it flips to a paid tier
 * or we hit the timeout. Webhooks usually land within 1-3s in test mode;
 * we poll for up to 30s, then show a "still processing" message.
 */

const POLL_INTERVAL_MS = 1500;
const POLL_TIMEOUT_MS = 30_000;

export default function CheckoutSuccessPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const sessionId = searchParams?.get("session_id") ?? null;

  const [elapsedMs, setElapsedMs] = useState(0);

  const subscription = trpc.billing.currentSubscription.useQuery(undefined, {
    refetchInterval: (query) => {
      const data = query.state.data;
      const tier = (data && (data as { tier?: string }).tier) || null;
      const isPaid = tier === "pro" || tier === "frontier";
      if (isPaid) return false;
      if (elapsedMs >= POLL_TIMEOUT_MS) return false;
      return POLL_INTERVAL_MS;
    },
    refetchOnWindowFocus: false,
  });

  // Tick a wallclock so refetchInterval can stop after the timeout.
  useEffect(() => {
    const startedAt = Date.now();
    const id = window.setInterval(() => {
      setElapsedMs(Date.now() - startedAt);
    }, 500);
    return () => window.clearInterval(id);
  }, []);

  const tier = useMemo(() => {
    const data = subscription.data;
    if (!data) return "free";
    return (data as { tier?: string }).tier ?? "free";
  }, [subscription.data]);

  const isPaid = tier === "pro" || tier === "frontier";
  const timedOut = !isPaid && elapsedMs >= POLL_TIMEOUT_MS;

  // Auto-redirect after a short victory pause.
  useEffect(() => {
    if (!isPaid) return;
    const id = window.setTimeout(() => {
      router.replace("/dashboard");
    }, 2500);
    return () => window.clearTimeout(id);
  }, [isPaid, router]);

  return (
    <div className="mx-auto max-w-xl py-16">
      <div className="bg-paper p-10 text-center">
        {isPaid ? (
          <>
            <CheckCircle2
              className="mx-auto h-12 w-12 text-emerald-600"
              aria-hidden
            />
            <h1 className="mt-4 font-display text-display-md text-ink">
              Welcome to Pro
            </h1>
            <p className="mt-3 font-sans text-[14px] text-graphite">
              Your subscription is active. Taking you to the dashboard…
            </p>
            <div className="mt-6">
              <button
                type="button"
                onClick={() => router.replace("/dashboard")}
                className="inline-flex items-center gap-2 rounded-full bg-ink px-5 py-2.5 font-sans text-[13px] text-paper hover:bg-ink/90"
              >
                Go to dashboard
              </button>
            </div>
          </>
        ) : timedOut ? (
          <>
            <h1 className="font-display text-display-md text-ink">
              Almost there…
            </h1>
            <p className="mt-3 font-sans text-[14px] text-graphite">
              Stripe is taking a moment to confirm your payment. Refresh
              this page in a few seconds, or head to the dashboard. Your
              workspace will upgrade automatically.
            </p>
            <div className="mt-6 flex justify-center gap-3">
              <button
                type="button"
                onClick={() => subscription.refetch()}
                className="inline-flex items-center gap-2 rounded-full border border-lattice px-5 py-2.5 font-sans text-[13px] text-ink hover:bg-paper-fold/50"
              >
                Refresh
              </button>
              <button
                type="button"
                onClick={() => router.replace("/dashboard")}
                className="inline-flex items-center gap-2 rounded-full bg-ink px-5 py-2.5 font-sans text-[13px] text-paper hover:bg-ink/90"
              >
                Go to dashboard
              </button>
            </div>
          </>
        ) : (
          <>
            <Loader2
              className="mx-auto h-10 w-10 animate-spin text-ink/70"
              aria-hidden
            />
            <h1 className="mt-4 font-display text-display-md text-ink">
              Confirming your subscription…
            </h1>
            <p className="mt-3 font-sans text-[14px] text-graphite">
              Stripe just told us payment succeeded. Hold tight while the
              webhook flips your workspace to Pro.
            </p>
            {sessionId && (
              <p className="mt-2 font-mono text-[11px] text-graphite-soft">
                {sessionId}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
