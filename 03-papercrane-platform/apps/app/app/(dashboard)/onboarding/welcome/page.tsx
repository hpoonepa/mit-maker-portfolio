/**
 * Step 1: Welcome (Wave 8).
 *
 * One-screen orientation. Three quick bullets describe what the next 6
 * screens will do, then a single primary CTA.
 *
 * Wave 8 adds a persona toggle (PI / grad student / industry). The choice
 * lands in `user_onboarding.persona` and downstream defaults adapt to it
 * (e.g. industry users default to audit-log opt-in on the dashboard).
 *
 * State writes happen on click: the page itself is server-friendly except
 * for the inline persona buttons.
 */
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { StepContainer } from "@/components/onboarding/StepContainer";
import {
  PERSONAS,
  type Persona,
  readClientCache,
  writeClientCache,
} from "@/lib/onboarding-state";
import { trpc } from "@/lib/trpc/client";

export default function WelcomePage() {
  const router = useRouter();
  const [persona, setPersona] = useState<Persona>("grad");
  const [submitting, setSubmitting] = useState(false);

  // Hydrate from server-known persona on mount, falling back to the local
  // cache so the toggle doesn't flash to the default for returning users.
  const progress = trpc.onboarding.getProgress.useQuery(undefined, {
    staleTime: 60_000,
  });
  const setStep = trpc.onboarding.setStep.useMutation();

  useEffect(() => {
    if (progress.data?.persona) {
      setPersona(progress.data.persona);
      return;
    }
    const cached = readClientCache();
    if (cached?.persona) setPersona(cached.persona);
  }, [progress.data?.persona]);

  async function handleStart() {
    setSubmitting(true);
    writeClientCache({ step: "create-org", persona });
    try {
      await setStep.mutateAsync({ step: "create-org", persona });
    } catch {
      // Server may not have the table yet; the local cache keeps the user
      // moving and the resume logic re-syncs once tRPC catches up.
    }
    router.push("/onboarding/create-org");
  }

  return (
    <StepContainer
      eyebrow="Step 01 / Welcome"
      title="Welcome to Paper Crane"
      subtitle="The shortest path from a PDB to a screenable protein binder."
      primary={{
        label: submitting ? "Starting…" : "Get started",
        onClick: handleStart,
        disabled: submitting,
      }}
      secondary={{ label: "Watch a demo", href: "/#demo" }}
    >
      <p>
        In the next few screens you'll set up an organisation, pick a
        target, fire off your first BindCraft run, optionally connect Modal
        for real GPUs, and invite teammates. Most teams finish in under
        five minutes.
      </p>

      <div>
        <p className="mb-3 font-sans text-[0.66rem] text-graphite">
          Which fits you best?
        </p>
        <div role="radiogroup" aria-label="Persona" className="grid gap-2 md:grid-cols-3">
          {PERSONAS.map((p) => {
            const active = persona === p.id;
            return (
              <button
                key={p.id}
                type="button"
                role="radio"
                aria-checked={active}
                data-testid={`persona-${p.id}`}
                onClick={() => setPersona(p.id)}
                className={[
                  "flex flex-col items-start gap-1 rounded-xl border p-3 text-left transition-all",
                  active
                    ? "border-crane bg-paper"
                    : "border-lattice bg-paper-fold/40 hover:bg-paper",
                ].join(" ")}
              >
                <span className="text-sm font-medium text-ink">{p.label}</span>
                <span className="text-xs text-graphite">{p.blurb}</span>
              </button>
            );
          })}
        </div>
        <p className="mt-2 text-[0.7rem] text-graphite-soft">
          This only sets the initial defaults. You can change them in Settings.
        </p>
      </div>

      <ul className="space-y-3 pl-5 text-sm">
        <li>
          <span className="font-mono text-xs text-crane">01 ·</span>{" "}
          <span className="text-ink">Create your org</span>: name it, pick a
          type, invite teammates later.
        </li>
        <li>
          <span className="font-mono text-xs text-crane">02 ·</span>{" "}
          <span className="text-ink">Pick a target</span>: upload a PDB or
          start from a preset (PD-L1, RBD, IL-7Rα).
        </li>
        <li>
          <span className="font-mono text-xs text-crane">03 ·</span>{" "}
          <span className="text-ink">Submit your first job</span> -
          BindCraft defaults, 8 seeds, ~20 min wall clock.
        </li>
      </ul>
      <p className="text-xs text-graphite">
        You can skip any step you want. Your progress saves automatically,
        so closing the tab won't lose your spot.
      </p>
    </StepContainer>
  );
}
