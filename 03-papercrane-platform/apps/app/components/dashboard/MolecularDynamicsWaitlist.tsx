"use client";

import { Check, Loader2 } from "lucide-react";
import { trpc } from "@/lib/trpc/client";

export function MolecularDynamicsWaitlist() {
  const status = trpc.feedback.molecularDynamicsWaitlist.useQuery();
  const join = trpc.feedback.joinMolecularDynamicsWaitlist.useMutation();
  const utils = trpc.useUtils();
  const joined = status.data?.joined || join.data?.joined;

  return (
    <section aria-labelledby="dynamics-heading" className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 py-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 id="dynamics-heading" className="text-sm text-ink">Molecular dynamics</h2>
        <span className="text-xs text-graphite">Coming soon</span>
      </div>
      {joined ? (
        <p role="status" className="inline-flex items-center gap-2 text-sm text-graphite"><Check aria-hidden="true" className="h-3.5 w-3.5" />You’re on the waitlist</p>
      ) : (
        <div>
          <button type="button" disabled={join.isPending || status.isLoading} onClick={() => join.mutate(undefined, {
            onSuccess: () => { void utils.feedback.molecularDynamicsWaitlist.invalidate(); },
          })} className="inline-flex min-h-10 items-center gap-2 text-sm text-crane hover:text-ink disabled:cursor-default disabled:opacity-60">
            {join.isPending && <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />}
            {status.isLoading ? "Checking waitlist…" : join.isPending ? "Joining…" : "Join waitlist"}
          </button>
          {join.error && <p role="alert" className="text-xs text-red-300">Couldn’t join. Please try again.</p>}
        </div>
      )}
    </section>
  );
}
