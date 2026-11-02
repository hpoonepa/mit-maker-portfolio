/**
 * Step 7: Done (Wave 8).
 *
 * Two personas land here:
 *   - submitted a job → show a "watch it stream" link to /jobs/<id>
 *   - skipped the job  → show a "submit one later" nudge
 *
 * Either way we mark the user complete via tRPC so the auth middleware
 * stops redirecting to /onboarding.
 *
 * Auto-redirect: after 4s on this screen, the user gets bounced to
 * `/dashboard` (the actual canonical landing route: `/home` is an alias).
 * If they click "Watch it stream" or any other action first, we cancel
 * the timer.
 */
"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { StepContainer } from "@/components/onboarding/StepContainer";
import { clearState, loadState } from "@/lib/onboarding/state";
import { clearClientCache } from "@/lib/onboarding-state";
import { trpc } from "@/lib/trpc/client";

const AUTO_REDIRECT_MS = 4000;

export default function DonePage() {
  const router = useRouter();
  const [jobId, setJobId] = useState<string | null>(null);
  const [skippedJob, setSkippedJob] = useState(false);
  const [completionError, setCompletionError] = useState<string | null>(null);
  const markComplete = trpc.onboarding.markComplete.useMutation();
  const initRef = useRef(false);
  const redirectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const persistCompletion = () => {
    setCompletionError(null);
    markComplete.mutate(undefined, {
      onSuccess: () => {
        clearState();
        clearClientCache();
        redirectTimerRef.current = setTimeout(() => {
          router.replace("/dashboard");
        }, AUTO_REDIRECT_MS);
      },
      onError: () => {
        setCompletionError(
          "We couldn't save your onboarding progress. Retry before leaving this page.",
        );
      },
    });
  };

  useEffect(() => {
    if (initRef.current) return;
    initRef.current = true;
    const s = loadState();
    setJobId(s?.submittedJobId ?? null);
    setSkippedJob(s?.skipped.includes("first-job") ?? false);

    // Do not clear the local recovery state or redirect until the durable
    // server write succeeds. A failed write stays visible and retryable.
    persistCompletion();
    return () => {
      if (redirectTimerRef.current) clearTimeout(redirectTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const primary = jobId
    ? { label: "Watch it stream", href: `/jobs/${jobId}` }
    : { label: "Go to dashboard", href: "/dashboard" };

  return (
    <div className="relative">
      {/* Quiet origami fold: a single still mark instead of confetti.
          Crease lines suggest a finished paper crane without animation noise. */}
      <div
        aria-hidden
        data-testid="origami-fold"
        className="pointer-events-none absolute left-1/2 top-0 -translate-x-1/2 -translate-y-2 opacity-80"
      >
        <svg width="44" height="44" viewBox="0 0 44 44" fill="none">
          <path
            d="M4 36 L22 6 L40 36 Z"
            stroke="#c1272d"
            strokeWidth="1.25"
            strokeLinejoin="round"
          />
          <path
            d="M22 6 L22 36 M4 36 L40 36 M22 36 L13 22 M22 36 L31 22"
            stroke="#c1272d"
            strokeWidth="0.75"
            strokeOpacity="0.55"
            strokeLinejoin="round"
          />
        </svg>
      </div>
      <StepContainer
        eyebrow="Step 07 / Done"
        title={jobId ? "Your first job is running" : "You're all set"}
        subtitle={
          jobId
            ? "We're allocating seeds now. Results stream in as each one finishes."
            : "Jump into the dashboard when you're ready to upload a target and run your first design."
        }
        primary={primary}
        secondary={{ label: "Invite teammates", href: "/settings/team" }}
      >
        {completionError && (
          <div
            role="alert"
            className="rounded-lg border border-crane/30 bg-crane-glow p-4 font-sans text-sm text-crane-deep"
          >
            <p>{completionError}</p>
            <button
              type="button"
              onClick={persistCompletion}
              disabled={markComplete.isPending}
              className="mt-3 font-medium underline underline-offset-4 disabled:opacity-50"
            >
              {markComplete.isPending ? "Saving…" : "Retry save"}
            </button>
          </div>
        )}

        {jobId ? (
          <div className="bg-paper p-5 font-mono text-xs">
            <div className="text-graphite">Job ID</div>
            <div className="mt-1 text-ink">{jobId}</div>
          </div>
        ) : skippedJob ? (
          <p className="text-sm text-graphite">
            You skipped the first run. Head to{" "}
            <Link href="/targets" className="text-crane hover:underline">
              Targets
            </Link>{" "}
            to upload a PDB, or visit{" "}
            <Link href="/jobs" className="text-crane hover:underline">
              Jobs
            </Link>{" "}
            when you're ready to submit.
          </p>
        ) : null}

        <div className="grid gap-3 text-sm md:grid-cols-2">
          <Tile
            title="Browse tools"
            body="BindCraft, BoltzGen, RFdiffusion, and more. Try the same target across tools."
            href="/tools"
          />
          <Tile
            title="Read the docs"
            body="Tier pricing, metric thresholds, and the BindCraft default config."
            href="/docs"
          />
        </div>

        <p className="text-center text-[0.66rem] uppercase tracking-[0.2em] text-graphite-soft">
          Heading to your dashboard automatically…
        </p>
      </StepContainer>
    </div>
  );
}

function Tile({
  title,
  body,
  href,
}: {
  title: string;
  body: string;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="p-4 transition-colors hover:border-lattice-strong hover:bg-paper"
    >
      <div className="font-display text-base text-ink">{title}</div>
      <div className="mt-1 text-xs text-graphite">{body}</div>
    </Link>
  );
}
