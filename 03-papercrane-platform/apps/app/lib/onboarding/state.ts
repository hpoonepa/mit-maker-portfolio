/**
 * Onboarding state machine + localStorage persistence.
 *
 * Shape
 * -----
 * The wizard is a 5-step linear flow. Two of those steps can be skipped
 * (`first-target`, `first-job`): skipping advances the pointer and records
 * the skip in `state.skipped` so the dashboard can nudge the user later.
 *
 * Why localStorage (not a DB write per step)
 * ------------------------------------------
 * We want the user to be able to close the tab mid-flow and come back
 * without losing their org name / selected preset. Hitting the server on
 * every field change would require a throwaway draft table; localStorage
 * keeps the server surface small and the round-trip cost zero.
 *
 * We only write the draft to Postgres at the moments that matter:
 *   - org creation (trpc `projects.create`, wrapped later)
 *   - target upload/select (trpc `targets.create`)
 *   - job submission (trpc `jobs.submit`)
 *   - `onboardingCompleted = true` when the user hits the done page
 *
 * Version key
 * -----------
 * `papercrane.onboarding.v1`: bump the `v1` suffix if the shape of the
 * persisted payload changes in a non-backward-compatible way, so stale
 * drafts get ignored instead of crashing the app.
 */

export const ONBOARDING_STEPS = [
  "welcome",
  "create-org",
  "first-target",
  "first-job",
  "done",
] as const;

export type OnboardingStep = (typeof ONBOARDING_STEPS)[number];

export type OrgType = "lab" | "industry" | "student";

export interface OrgDraft {
  name: string;
  type: OrgType;
}

export type TargetDraft =
  | { source: "preset"; presetId: string; pdbId: string }
  | { source: "upload"; fileName: string };

export interface OnboardingState {
  step: OnboardingStep;
  orgDraft: OrgDraft;
  targetDraft: TargetDraft | null;
  skipped: OnboardingStep[];
  submittedJobId: string | null;
}

const STORAGE_KEY = "papercrane.onboarding.v1";

const SKIPPABLE_STEPS: ReadonlySet<OnboardingStep> = new Set<OnboardingStep>([
  "first-target",
  "first-job",
]);

export function createOnboardingState(): OnboardingState {
  return {
    step: "welcome",
    orgDraft: { name: "", type: "lab" },
    targetDraft: null,
    skipped: [],
    submittedJobId: null,
  };
}

export function isStepSkippable(step: OnboardingStep): boolean {
  return SKIPPABLE_STEPS.has(step);
}

function stepIndex(step: OnboardingStep): number {
  return ONBOARDING_STEPS.indexOf(step);
}

export function advance(state: OnboardingState): OnboardingState {
  const idx = stepIndex(state.step);
  if (idx < 0 || idx >= ONBOARDING_STEPS.length - 1) return state;
  const next = ONBOARDING_STEPS[idx + 1];
  return next ? { ...state, step: next } : state;
}

export function goBack(state: OnboardingState): OnboardingState {
  const idx = stepIndex(state.step);
  if (idx <= 0) return state;
  const prev = ONBOARDING_STEPS[idx - 1];
  return prev ? { ...state, step: prev } : state;
}

export function skip(state: OnboardingState): OnboardingState {
  if (!isStepSkippable(state.step)) return state;
  const skipped = state.skipped.includes(state.step)
    ? state.skipped
    : [...state.skipped, state.step];
  return { ...advance(state), skipped };
}

export function updateOrgDraft(
  state: OnboardingState,
  patch: Partial<OrgDraft>,
): OnboardingState {
  return { ...state, orgDraft: { ...state.orgDraft, ...patch } };
}

export function updateTargetDraft(
  state: OnboardingState,
  draft: TargetDraft | null,
): OnboardingState {
  return { ...state, targetDraft: draft };
}

export function markSubmitted(
  state: OnboardingState,
  jobId: string,
): OnboardingState {
  return { ...state, submittedJobId: jobId };
}

export function progressPercent(step: OnboardingStep): number {
  const idx = stepIndex(step);
  if (idx < 0) return 0;
  return Math.round((idx / (ONBOARDING_STEPS.length - 1)) * 100);
}

// ---- persistence -----------------------------------------------------------

function hasLocalStorage(): boolean {
  try {
    return typeof globalThis.localStorage !== "undefined";
  } catch {
    return false;
  }
}

function isOnboardingStep(v: unknown): v is OnboardingStep {
  return typeof v === "string" && (ONBOARDING_STEPS as readonly string[]).includes(v);
}

export function loadState(): OnboardingState | null {
  if (!hasLocalStorage()) return null;
  const raw = globalThis.localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<OnboardingState>;
    if (!isOnboardingStep(parsed.step)) return null;
    // Fill in defaults for anything missing so callers never get a partial.
    const base = createOnboardingState();
    return {
      step: parsed.step,
      orgDraft: parsed.orgDraft ?? base.orgDraft,
      targetDraft: parsed.targetDraft ?? null,
      skipped: Array.isArray(parsed.skipped)
        ? parsed.skipped.filter(isOnboardingStep)
        : [],
      submittedJobId: parsed.submittedJobId ?? null,
    };
  } catch {
    return null;
  }
}

export function saveState(state: OnboardingState): void {
  if (!hasLocalStorage()) return;
  globalThis.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

export function clearState(): void {
  if (!hasLocalStorage()) return;
  globalThis.localStorage.removeItem(STORAGE_KEY);
}
