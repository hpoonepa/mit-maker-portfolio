/**
 * /onboarding: resume dispatcher.
 *
 * The auth middleware funnels every "user without onboardingCompleted"
 * here. We don't want to dump them at step 1 every time, so this page
 * loads their `user_onboarding` row and pushes them to the right step.
 *
 * Server-rendered to avoid a client-side flash of the welcome card.
 *
 * Fallback chain:
 *   1. tRPC `getProgress` → if it returns a `currentStep`, jump there.
 *   2. If the row is missing or the call fails (e.g. migration hasn't
 *      run yet in dev), redirect to `welcome`: same as a brand-new user.
 */
import { redirect } from "next/navigation";
import { createServerTrpc } from "@/lib/trpc/server";
import { resolveResumeStep, stepHref } from "@/lib/onboarding-state";

export const dynamic = "force-dynamic";

export default async function OnboardingIndexPage() {
  let resumeHref = "/onboarding/welcome";
  let completed = false;
  try {
    const trpc = await createServerTrpc();
    const progress = await trpc.onboarding.getProgress.query();
    if (progress?.completed) {
      completed = true;
    } else {
      const step = resolveResumeStep({
        savedStep: progress?.currentStep ?? null,
        invitedToOrg: Boolean(progress?.orgId),
      });
      resumeHref = stepHref(step);
    }
  } catch {
    // Auth-middleware redirect or DB blip: start at welcome.
  }
  redirect(completed ? "/dashboard" : resumeHref);
}
