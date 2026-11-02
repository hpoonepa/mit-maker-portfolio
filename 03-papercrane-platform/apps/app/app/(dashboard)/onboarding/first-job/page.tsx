/**
 * Step 4: Submit the first real design job.
 *
 * Wired to `trpc.jobs.submit`. The tool is pinned to `bindcraft`, which is
 * on `VERIFIED_RUNNABLE_TOOL_SLUGS` (packages/trpc/src/config/toolReadiness.ts)
 * and on the free-tier allowlist: the server rejects anything else with
 * PRECONDITION_FAILED, so onboarding must never default outside that list.
 *
 * Request shape (see DesignRequestSchema in packages/types/src/design.ts):
 *   { toolId: "bindcraft",
 *     request: { targetPdb, targetChain?, hotspots?, seeds, numDesigns,
 *                toolParams: { targetId } } }
 *
 * `toolParams.targetId` is the UUID written by the previous step; the server
 * resolves it under RLS so the job carries verified target provenance rather
 * than guessing from the PDB id.
 *
 * Seeds are capped server-side at 25 per job (MAX_SEEDS_PER_JOB); we ask for
 * 8, which matches the preview card and keeps the first run cheap.
 *
 * Skippable: users who only want to look around can skip; we still advance
 * onboarding and land them on the dashboard.
 */
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { StepContainer } from "@/components/onboarding/StepContainer";
import { JobPreviewCard } from "@/components/onboarding/JobPreviewCard";
import {
  advance,
  createOnboardingState,
  loadState,
  markSubmitted,
  saveState,
  skip,
} from "@/lib/onboarding/state";
import { trpc } from "@/lib/trpc/client";
import { writeClientCache } from "@/lib/onboarding-state";

// ── Hand-off record written by /onboarding/first-target ─────────────────────

const TARGET_RECORD_KEY = "papercrane.onboarding.target.v1";

interface JobHotspot {
  chain: string;
  residues: number[];
}

interface OnboardingTargetRecord {
  targetId: string;
  name: string;
  pdbId: string | null;
  chain: string | null;
  hotspots: JobHotspot[];
}

function isHotspot(v: unknown): v is JobHotspot {
  if (!v || typeof v !== "object") return false;
  const h = v as Record<string, unknown>;
  return (
    typeof h.chain === "string" &&
    h.chain.length === 1 &&
    Array.isArray(h.residues) &&
    h.residues.every((r) => Number.isInteger(r))
  );
}

function readTargetRecord(): OnboardingTargetRecord | null {
  try {
    if (typeof globalThis.localStorage === "undefined") return null;
    const raw = globalThis.localStorage.getItem(TARGET_RECORD_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<OnboardingTargetRecord>;
    if (typeof parsed.targetId !== "string" || parsed.targetId.length === 0) {
      return null;
    }
    return {
      targetId: parsed.targetId,
      name: typeof parsed.name === "string" ? parsed.name : "Your target",
      pdbId: typeof parsed.pdbId === "string" ? parsed.pdbId : null,
      chain:
        typeof parsed.chain === "string" && parsed.chain.length === 1
          ? parsed.chain
          : null,
      hotspots: Array.isArray(parsed.hotspots)
        ? parsed.hotspots.filter(isHotspot)
        : [],
    };
  } catch {
    return null;
  }
}

// ── Run defaults ────────────────────────────────────────────────────────────

/** Must stay inside VERIFIED_RUNNABLE_TOOL_SLUGS and the free-tier allowlist. */
const ONBOARDING_TOOL_ID = "bindcraft";
const SEED_COUNT = 8; // mirrors JobPreviewCard; server caps at 25/job.

function humanError(err: unknown): string {
  const raw = err instanceof Error ? err.message.trim() : "";
  if (!raw) return "We couldn't start the run. Please try again.";
  if (/not allowed for tier/i.test(raw)) {
    return "Your plan can't run this tool yet. Skip this step and pick a tool from the Tools page.";
  }
  if (/not yet runnable/i.test(raw)) {
    return "That tool isn't available for real runs yet. Skip for now and browse the Tools page.";
  }
  if (/target not found/i.test(raw)) {
    return "We couldn't find the target you created. Go back and pick a target again.";
  }
  if (/quota|credit|budget|cost/i.test(raw)) {
    return `This run would exceed your compute allowance: ${raw}`;
  }
  if (/UNAUTHORIZED|not signed in/i.test(raw)) {
    return "Your session expired. Reload the page and sign in again.";
  }
  return raw;
}

interface SubmittedJob {
  id: string;
  status: string;
  etaSeconds: number;
}

export default function FirstJobPage() {
  const router = useRouter();
  const [target, setTarget] = useState<OnboardingTargetRecord | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<SubmittedJob | null>(null);

  const setStep = trpc.onboarding.setStep.useMutation();
  const submitJob = trpc.jobs.submit.useMutation();

  useEffect(() => {
    setTarget(readTargetRecord());
    setLoaded(true);
  }, []);

  async function persistAndGo() {
    writeClientCache({ step: "invite-team", persona: null });
    try {
      await setStep.mutateAsync({ step: "invite-team" });
    } catch {
      // ignore: server may not have the table yet
    }
    router.push("/onboarding/invite-team");
  }

  async function handleSubmit() {
    if (submitting || !target) return;
    setError(null);
    setSubmitting(true);
    try {
      const result = await submitJob.mutateAsync({
        toolId: ONBOARDING_TOOL_ID,
        request: {
          // 4-char RCSB id when we have one; the worker resolves the
          // structure from the target row otherwise.
          ...(target.pdbId ? { targetPdb: target.pdbId } : {}),
          ...(target.chain ? { targetChain: target.chain } : {}),
          ...(target.hotspots.length > 0 ? { hotspots: target.hotspots } : {}),
          seeds: Array.from({ length: SEED_COUNT }, (_, i) => i + 1),
          numDesigns: SEED_COUNT,
          toolParams: { targetId: target.targetId },
        },
      });

      const submitted: SubmittedJob = {
        id: result.id,
        status: result.status,
        etaSeconds: result.etaSeconds,
      };
      setJob(submitted);

      // Advance onboarding state up-front so a refresh doesn't resubmit.
      const base = loadState() ?? createOnboardingState();
      saveState(
        advance(markSubmitted({ ...base, step: "first-job" }, submitted.id)),
      );
      writeClientCache({ step: "invite-team", persona: null });
      try {
        await setStep.mutateAsync({ step: "invite-team" });
      } catch {
        // ignore: the local state carries the flow
      }
    } catch (err) {
      setError(humanError(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSkip() {
    if (submitting) return;
    const base = loadState() ?? createOnboardingState();
    saveState(skip({ ...base, step: "first-job" }));
    await persistAndGo();
  }

  // ── Submitted ─────────────────────────────────────────────────────────────
  if (job) {
    const etaMinutes = Math.max(1, Math.round(job.etaSeconds / 60));
    return (
      <StepContainer
        eyebrow="Step 04 / Submit"
        title="Your first run is queued"
        subtitle="It's running on our GPUs now. You can close this tab: results keep arriving without you."
        primary={{
          label: "Continue setup",
          onClick: () => {
            void persistAndGo();
          },
        }}
        secondary={{ label: "Watch it run", href: `/app/jobs/${job.id}` }}
      >
        <div
          data-testid="job-submitted"
          className="rounded-lg border border-crane bg-paper p-6"
        >
          <p className="font-sans text-[0.66rem] text-crane">
            Submitted
          </p>
          <dl className="mt-4 grid gap-4 text-sm md:grid-cols-3">
            <div>
              <dt className="font-sans text-[0.66rem] text-graphite-soft">
                Job ID
              </dt>
              <dd
                data-testid="job-id"
                className="mt-1 break-all font-mono text-sm text-ink"
              >
                {job.id}
              </dd>
            </div>
            <div>
              <dt className="font-sans text-[0.66rem] text-graphite-soft">
                Status
              </dt>
              <dd className="mt-1 font-display text-xl text-ink">
                {job.status}
              </dd>
            </div>
            <div>
              <dt className="font-sans text-[0.66rem] text-graphite-soft">
                Est. finish
              </dt>
              <dd className="mt-1 font-display text-xl text-ink">
                ~{etaMinutes} min
              </dd>
            </div>
          </dl>
          <p className="mt-5 text-sm leading-relaxed text-graphite">
            &ldquo;Queued&rdquo; means it&rsquo;s waiting for a free GPU;
            it&rsquo;ll move to &ldquo;running&rdquo; on its own. Designs stream
            in one at a time as each seed finishes.
          </p>
          <Link
            href={`/app/jobs/${job.id}`}
            data-testid="watch-job-link"
            className="mt-5 inline-flex items-center justify-center rounded-full bg-crane px-6 py-3 text-sm font-medium text-paper transition-all hover:bg-crane-deep"
          >
            Watch it run
          </Link>
        </div>
      </StepContainer>
    );
  }

  // ── No target yet ─────────────────────────────────────────────────────────
  if (loaded && !target) {
    return (
      <StepContainer
        eyebrow="Step 04 / Submit"
        title="Pick a target first"
        subtitle="A run needs something to design against, so this step needs a target."
        primary={{
          label: "Pick a target",
          href: "/onboarding/first-target",
        }}
        secondary={{ label: "Back", href: "/onboarding/first-target" }}
        skip={{ label: "Skip: I'll run one later", onClick: handleSkip }}
      >
        <div
          data-testid="no-target"
          className="bg-paper p-6 text-sm leading-relaxed text-graphite"
        >
          <p>
            You skipped the target step (or the draft was cleared). Go back and
            hit <span className="text-ink">&ldquo;Use the example
            target&rdquo;</span>. It takes one click and needs no typing.
          </p>
          <p className="mt-3 text-xs text-graphite-soft">
            You can also skip ahead and start a run later from the Tools page.
          </p>
        </div>
      </StepContainer>
    );
  }

  // ── Ready to submit ───────────────────────────────────────────────────────
  return (
    <StepContainer
      eyebrow="Step 04 / Submit"
      title="Your first run, ready to go"
      subtitle="We've pre-filled a sensible default. You can tune every knob on the Tools page later."
      secondary={{ label: "Back", href: "/onboarding/first-target" }}
      skip={{
        label: "Skip: I'll run one later",
        onClick: handleSkip,
        disabled: submitting,
      }}
    >
      <div className="p-5 text-sm leading-relaxed text-graphite">
        <p>
          <span className="text-ink">What happens when you press submit:</span>{" "}
          we send your target to a GPU and let BindCraft invent{" "}
          {SEED_COUNT} candidate mini-proteins that should stick to it. Each
          candidate is folded and scored, so you get shapes plus a confidence
          number: not just a list of letters.
        </p>
        <p className="mt-3">
          It usually takes <span className="text-ink">about 20 minutes</span>.
          You don&rsquo;t have to wait here: results appear on the job page as
          they finish, and nothing is lost if you close the tab.
        </p>
        {target && target.hotspots.length > 0 ? (
          <p className="mt-3 text-xs text-graphite-soft">
            We&rsquo;re aiming at{" "}
            {target.hotspots
              .map((h) => `chain ${h.chain} residues ${h.residues.join(", ")}`)
              .join("; ")}{" "}
            . These are the hotspots, or the specific patch of the target the
            binder should touch.
          </p>
        ) : (
          <p className="mt-3 text-xs text-graphite-soft">
            No hotspots were marked on this target, so the designer is free to
            pick its own contact patch. You can mark hotspots later on the
            target page for a more focused run.
          </p>
        )}
      </div>

      {loaded && target ? (
        <JobPreviewCard
          targetLabel={target.pdbId ?? target.name}
          onSubmit={() => {
            void handleSubmit();
          }}
          submitting={submitting}
        />
      ) : (
        <div className="bg-paper p-6 text-sm text-graphite">
          Loading your target…
        </div>
      )}

      {error && (
        <p
          data-testid="job-error"
          role="alert"
          className="rounded-xl border border-crane/40 bg-crane-glow/40 px-4 py-3 text-sm text-crane-deep"
        >
          {error}
        </p>
      )}
    </StepContainer>
  );
}
