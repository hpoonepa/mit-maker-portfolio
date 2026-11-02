/**
 * Onboarding state: server-side persistence helpers (Wave 8).
 *
 * This module sits on top of the existing client-side state machine in
 * `lib/onboarding/state.ts`. It mirrors the wizard's pointer + persona
 * choice into a `user_onboarding` row so we can:
 *   1. Resume the wizard from any device (the previous version only
 *      remembered drafts in localStorage on the same browser).
 *   2. Tell the auth middleware whether a user has finished, without
 *      relying on the legacy `onboardingCompleted` boolean column.
 *   3. Personalise downstream defaults based on the welcome-step persona
 *      (PI / grad student / industry).
 *
 * Schema is added in `prisma/migrations/wave8_onboarding_state` -
 * Agent 1 owns the actual `prisma migrate` invocation.
 */

import {
  ONBOARDING_STEPS as LEGACY_STEPS,
  type OnboardingStep as LegacyStep,
} from "./onboarding/state";

// ── Step taxonomy ──────────────────────────────────────────────────────────

/**
 * Wave 8 introduced Modal BYOK as an optional step. Beta users now run on
 * Paper Crane's system Modal workspace by default, so `connect-modal` remains
 * accepted for older saved sessions but is no longer part of the main wizard.
 * The remaining optional step is:
 *   - `invite-team`   : add teammates by email (skip → solo workspace)
 *
 * The legacy 5-step set is preserved so older sessions don't 404 mid-flow.
 * `WIZARD_STEPS` is the canonical order the UI walks through; `ALL_STEPS`
 * is the union accepted by the persistence layer.
 */
export const WIZARD_STEPS = [
  "welcome",
  "create-org",
  "first-target",
  "first-job",
  "invite-team",
  "done",
] as const;

export type WizardStep = (typeof WIZARD_STEPS)[number];

type LegacyModalStep = "connect-modal";

export const ALL_STEPS = Array.from(
  new Set<string>([...LEGACY_STEPS, ...WIZARD_STEPS, "connect-modal"]),
) as readonly (LegacyStep | WizardStep | LegacyModalStep)[];

export type Persona = "pi" | "grad" | "industry";

export const PERSONAS: ReadonlyArray<{
  id: Persona;
  label: string;
  blurb: string;
}> = [
  {
    id: "pi",
    label: "PI / faculty",
    blurb: "Running a lab, picking targets, paying for compute.",
  },
  {
    id: "grad",
    label: "Grad student / postdoc",
    blurb: "Hands-on with structures, MD, and benchmarks.",
  },
  {
    id: "industry",
    label: "Industry / biotech",
    blurb: "Pipeline work: IP-safe, audit logs, CSV export.",
  },
];

export const SKIPPABLE_WIZARD_STEPS: ReadonlySet<WizardStep> = new Set<WizardStep>([
  "first-target",
  "first-job",
  "invite-team",
]);

// ── Step navigation ────────────────────────────────────────────────────────

export function isWizardStep(v: unknown): v is WizardStep {
  return typeof v === "string" && (WIZARD_STEPS as readonly string[]).includes(v);
}

function normalizeWizardStep(v: unknown): WizardStep {
  if (v === "connect-modal") return "invite-team";
  return isWizardStep(v) ? v : "welcome";
}

export function nextStep(step: WizardStep): WizardStep | null {
  const i = WIZARD_STEPS.indexOf(step);
  if (i < 0 || i >= WIZARD_STEPS.length - 1) return null;
  return WIZARD_STEPS[i + 1] ?? null;
}

export function prevStep(step: WizardStep): WizardStep | null {
  const i = WIZARD_STEPS.indexOf(step);
  if (i <= 0) return null;
  return WIZARD_STEPS[i - 1] ?? null;
}

export function isStepSkippable(step: WizardStep): boolean {
  return SKIPPABLE_WIZARD_STEPS.has(step);
}

export function stepHref(step: WizardStep): string {
  return `/onboarding/${step}`;
}

/**
 * Resume policy:
 *   - if no row exists, start at `welcome`
 *   - if `current_step === "done"`, the user is done: caller should redirect
 *     them out of the wizard
 *   - otherwise, return the saved step
 *
 * `invitedToOrg` short-circuits step 2 (we don't ask people to create an org
 * if they joined via an invite link: they're already in one).
 */
export function resolveResumeStep(opts: {
  savedStep: WizardStep | null;
  invitedToOrg: boolean;
}): WizardStep {
  const saved = opts.savedStep;
  if (!saved || saved === "welcome") {
    return opts.invitedToOrg ? "first-target" : "welcome";
  }
  if (saved === "create-org" && opts.invitedToOrg) {
    // The user is mid-flow but their invite was accepted in the meantime.
    return "first-target";
  }
  return saved;
}

// ── Server-side persistence (DB) ───────────────────────────────────────────

/**
 * Shape the API surfaces to the wizard. Callers shouldn't need to know
 * about Prisma column names.
 */
export interface OnboardingProgress {
  userId: string;
  orgId: string | null;
  currentStep: WizardStep;
  persona: Persona | null;
  completed: boolean;
  lastUpdatedAt: Date;
}

/**
 * Minimal Prisma-compatible interface: we only depend on the methods the
 * resolvers actually call. Keeping this loose lets the unit tests pass a
 * fake without dragging the full PrismaClient type in.
 */
export interface OnboardingDelegate {
  findUnique(args: { where: { userId: string } }): Promise<{
    userId: string;
    orgId: string | null;
    currentStep: string;
    persona: string | null;
    completedAt: Date | null;
    lastUpdatedAt: Date;
  } | null>;
  upsert(args: {
    where: { userId: string };
    update: {
      currentStep?: string;
      persona?: string | null;
      orgId?: string | null;
      completedAt?: Date | null;
      lastUpdatedAt: Date;
    };
    create: {
      userId: string;
      currentStep: string;
      persona: string | null;
      orgId: string | null;
      completedAt: Date | null;
      lastUpdatedAt: Date;
    };
  }): Promise<unknown>;
}

function rowToProgress(row: {
  userId: string;
  orgId: string | null;
  currentStep: string;
  persona: string | null;
  completedAt: Date | null;
  lastUpdatedAt: Date;
}): OnboardingProgress {
  const step = normalizeWizardStep(row.currentStep);
  const persona: Persona | null =
    row.persona === "pi" || row.persona === "grad" || row.persona === "industry"
      ? row.persona
      : null;
  return {
    userId: row.userId,
    orgId: row.orgId,
    currentStep: step,
    persona,
    completed: row.completedAt != null,
    lastUpdatedAt: row.lastUpdatedAt,
  };
}

export async function getProgress(
  delegate: OnboardingDelegate,
  userId: string,
): Promise<OnboardingProgress | null> {
  const row = await delegate.findUnique({ where: { userId } });
  return row ? rowToProgress(row) : null;
}

export interface SetStepInput {
  step: WizardStep;
  persona?: Persona | null;
  orgId?: string | null;
}

export async function setStep(
  delegate: OnboardingDelegate,
  userId: string,
  input: SetStepInput,
): Promise<OnboardingProgress> {
  if (!isWizardStep(input.step)) {
    throw new Error(`unknown onboarding step: ${input.step}`);
  }
  const now = new Date();
  const completedAt = input.step === "done" ? now : null;

  await delegate.upsert({
    where: { userId },
    update: {
      currentStep: input.step,
      ...(input.persona !== undefined ? { persona: input.persona } : {}),
      ...(input.orgId !== undefined ? { orgId: input.orgId } : {}),
      completedAt,
      lastUpdatedAt: now,
    },
    create: {
      userId,
      currentStep: input.step,
      persona: input.persona ?? null,
      orgId: input.orgId ?? null,
      completedAt,
      lastUpdatedAt: now,
    },
  });

  return {
    userId,
    orgId: input.orgId ?? null,
    currentStep: input.step,
    persona: input.persona ?? null,
    completed: completedAt != null,
    lastUpdatedAt: now,
  };
}

// ── Client-side localStorage bridge ────────────────────────────────────────

/**
 * Lightweight client cache so the wizard renders the right step within a
 * single tick, before the tRPC `getProgress` round-trip completes. The
 * server is the source of truth: this is only for paint speed.
 */
const CLIENT_KEY = "papercrane.onboarding.wave8.v1";

export interface ClientCache {
  step: WizardStep;
  persona: Persona | null;
}

export function readClientCache(): ClientCache | null {
  try {
    if (typeof globalThis.localStorage === "undefined") return null;
    const raw = globalThis.localStorage.getItem(CLIENT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ClientCache>;
    if (!isWizardStep(parsed.step) && parsed.step !== "connect-modal") return null;
    const persona =
      parsed.persona === "pi" ||
      parsed.persona === "grad" ||
      parsed.persona === "industry"
        ? parsed.persona
        : null;
    return { step: normalizeWizardStep(parsed.step), persona };
  } catch {
    return null;
  }
}

export function writeClientCache(cache: ClientCache): void {
  try {
    if (typeof globalThis.localStorage === "undefined") return;
    globalThis.localStorage.setItem(CLIENT_KEY, JSON.stringify(cache));
  } catch {
    // Quota / private mode: just drop the cache write, server still wins.
  }
}

export function clearClientCache(): void {
  try {
    if (typeof globalThis.localStorage === "undefined") return;
    globalThis.localStorage.removeItem(CLIENT_KEY);
  } catch {
    // ignore
  }
}
