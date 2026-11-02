/**
 * Step 2: Create first org (Wave 8).
 *
 * Users coming from signup already have a user row but no org. We ask for
 * the bare minimum: name + type. Seats, billing, and slug refinement can
 * happen later on the settings page.
 *
 * If the user landed here via an invite link, we short-circuit this step:
 * they're already in an org, so we forward straight to step 3.
 *
 * The workspace is created server-side by `onboarding.createWorkspace`
 * (input: `{ name, type }`). That mutation is idempotent: a user who
 * already belongs to an org gets their existing org back with
 * `created: false` rather than a duplicate. We only advance the wizard
 * after it resolves; local drafts are written on success so a failed
 * attempt can't leave the client claiming a workspace that doesn't exist.
 */
"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { StepContainer } from "@/components/onboarding/StepContainer";
import {
  createOnboardingState,
  loadState,
  saveState,
  updateOrgDraft,
  advance,
  type OrgType,
} from "@/lib/onboarding/state";
import { trpc } from "@/lib/trpc/client";
import { writeClientCache } from "@/lib/onboarding-state";

const ORG_TYPES: { id: OrgType; label: string; blurb: string }[] = [
  { id: "lab", label: "Academic lab", blurb: "PI + grad students + postdocs" },
  { id: "industry", label: "Industry team", blurb: "Biotech, pharma, or TechBio co." },
  { id: "student", label: "Student / solo", blurb: "iGEM, coursework, personal project" },
];

const MAX_NAME_LENGTH = 80;

/**
 * Turn a tRPC/network failure into something a first-time user can act on.
 * We never surface raw error payloads: they read as scary nonsense to
 * someone who has never seen a stack trace.
 */
function friendlyCreateError(err: unknown): string {
  const raw = err instanceof Error ? err.message.toLowerCase() : "";
  if (raw.includes("unauthorized") || raw.includes("unauthenticated")) {
    return "Your sign-in seems to have expired. Refresh the page and sign in again.";
  }
  if (raw.includes("slug") || raw.includes("conflict") || raw.includes("unique")) {
    return "That name is already taken. Try adding your institution or team to it.";
  }
  if (raw.includes("failed to fetch") || raw.includes("network")) {
    return "We couldn't reach Paper Crane. Check your internet connection and try again.";
  }
  return "We couldn't create your workspace just now. Please try again in a moment.";
}

export default function CreateOrgPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [type, setType] = useState<OrgType>("lab");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const progress = trpc.onboarding.getProgress.useQuery(undefined, {
    staleTime: 60_000,
  });
  const setStep = trpc.onboarding.setStep.useMutation();
  const createWorkspace = trpc.onboarding.createWorkspace.useMutation();

  // Default the org-type radio to a sensible choice based on persona.
  const defaultType = useMemo<OrgType>(() => {
    switch (progress.data?.persona) {
      case "industry":
        return "industry";
      case "pi":
        return "lab";
      case "grad":
        return "lab";
      default:
        return "lab";
    }
  }, [progress.data?.persona]);

  // Hydrate from localStorage on mount so refreshes are non-destructive.
  useEffect(() => {
    const saved = loadState();
    if (saved?.orgDraft && saved.orgDraft.name) {
      setName(saved.orgDraft.name);
      setType(saved.orgDraft.type);
    } else {
      setType(defaultType);
    }
  }, [defaultType]);

  // If the user is already in an org (e.g. invited), skip this step.
  useEffect(() => {
    if (progress.data?.orgId) {
      router.replace("/onboarding/first-target");
    }
  }, [progress.data?.orgId, router]);

  async function handleCreate() {
    const trimmed = name.trim();

    // Boundary validation: mirror the server's Zod rules so the user gets a
    // friendly message instead of a round-trip rejection.
    if (!trimmed) {
      setError("Give your workspace a name so your team knows where they are.");
      return;
    }
    if (trimmed.length > MAX_NAME_LENGTH) {
      setError(`That name is a bit long: keep it under ${MAX_NAME_LENGTH} characters.`);
      return;
    }

    setError(null);
    setSubmitting(true);
    try {
      // Real workspace creation. Idempotent server-side: if this user is
      // already in an org we get that org back instead of a duplicate.
      await createWorkspace.mutateAsync({ name: trimmed, type });
    } catch (err) {
      setError(friendlyCreateError(err));
      setSubmitting(false);
      return; // Stay on this step: nothing was created.
    }

    // Only now do we advance the wizard.
    const base = loadState() ?? createOnboardingState();
    const next = advance(updateOrgDraft(base, { name: trimmed, type }));
    saveState(next);
    writeClientCache({ step: "first-target", persona: progress.data?.persona ?? null });
    try {
      await setStep.mutateAsync({ step: "first-target" });
    } catch {
      // Non-blocking: the workspace exists and localStorage has the draft,
      // so resume logic will re-sync the step on the next page.
    }
    router.push("/onboarding/first-target");
  }

  return (
    <StepContainer
      eyebrow="Step 02 / Organisation"
      title="Name your workspace"
      subtitle="A workspace holds your targets, jobs, and results. Create one before starting a run."
      primary={{
        label: submitting ? "Creating your workspace…" : "Create workspace",
        onClick: handleCreate,
        disabled: !name.trim() || submitting,
      }}
      secondary={{ label: "Back", href: "/onboarding/welcome" }}
    >
      <div className="space-y-5">
        <label className="block">
          <span className="mb-2 block font-sans text-[0.66rem] text-graphite">
            Workspace name
          </span>
          <input
            type="text"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              if (error) setError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !submitting) void handleCreate();
            }}
            placeholder="Acme Bio"
            maxLength={MAX_NAME_LENGTH}
            autoFocus
            aria-invalid={Boolean(error)}
            data-testid="org-name"
            className={[
              "w-full rounded-xl border bg-paper px-4 py-3 font-display text-xl text-ink placeholder:text-graphite-soft focus:border-crane focus:outline-none focus:ring-2 focus:ring-crane-glow",
              error ? "border-crane" : "border-lattice",
            ].join(" ")}
          />
          <span className="mt-2 block text-xs text-graphite">
            Use your lab, company, or project name. Nothing here is permanent -
            you can rename it later in Settings.
          </span>
          {error && (
            <p className="mt-2 text-xs text-crane-deep" role="alert">
              {error}
            </p>
          )}
        </label>

        <div>
          <span className="mb-2 block font-sans text-[0.66rem] text-graphite">
            What kind of team is this?
          </span>
          <span className="mb-2 block text-xs text-graphite">
            This only helps us pick sensible defaults for you. It doesn&apos;t
            limit what you can do, and you can change it later.
          </span>
          <div role="radiogroup" className="grid gap-2 md:grid-cols-3">
            {ORG_TYPES.map((t) => {
              const active = type === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => setType(t.id)}
                  className={[
                    "flex flex-col items-start gap-1 rounded-xl border p-3 text-left transition-all",
                    active
                      ? "border-crane bg-paper"
                      : "border-lattice bg-paper-fold/40 hover:bg-paper",
                  ].join(" ")}
                >
                  <span className="text-sm font-medium text-ink">{t.label}</span>
                  <span className="text-xs text-graphite">{t.blurb}</span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="p-4 text-sm text-graphite">
          <p>
            <span className="text-ink">What happens next:</span> we create the
            workspace, make you its owner, and take you to the next step where
            you&apos;ll pick a protein target to design against.
          </p>
          <p className="mt-2 text-xs text-graphite-soft">
            Nothing is billed and no jobs run during setup.
          </p>
        </div>
      </div>
    </StepContainer>
  );
}
