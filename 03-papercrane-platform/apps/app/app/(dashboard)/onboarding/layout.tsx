/**
 * Full-viewport onboarding shell.
 *
 * Strips the dashboard sidebar + chrome: first-run users should see only
 * the wizard so they can't get lost in an empty dashboard state. The
 * progress bar sits at the top; the step itself is a centered card.
 *
 * Step detection
 * --------------
 * We derive the current step from the URL (`/onboarding/<step>`) so the
 * layout stays a server component and doesn't need to read client state.
 * This also keeps the progress bar honest if the user deep-links into a
 * specific step.
 */
import Link from "next/link";
import type { ReactNode } from "react";
import { headers } from "next/headers";
import { WIZARD_STEPS, type WizardStep } from "@/lib/onboarding-state";
import { ProgressBar } from "@/components/onboarding/ProgressBar";

function parseStepFromPath(path: string): WizardStep {
  const last = path.replace(/\/$/, "").split("/").pop() ?? "";
  return (WIZARD_STEPS as readonly string[]).includes(last)
    ? (last as WizardStep)
    : "welcome";
}

export default async function OnboardingLayout({
  children,
}: {
  children: ReactNode;
}) {
  // next-app "headers" gives us the current request URL via the `x-url`
  // header the framework injects in layouts. This avoids pulling in a
  // client component just to read the pathname.
  const h = await headers();
  const pathname = h.get("x-invoke-path") ?? h.get("x-url") ?? "";
  const currentStep = parseStepFromPath(pathname);

  return (
    <div className="min-h-screen bg-paper text-ink">
      <div className="mx-auto flex min-h-screen max-w-4xl flex-col gap-10 px-6 pb-16 pt-10 md:pt-16">
        <header className="flex items-center justify-between">
          <Link
            href="/"
            className="font-display text-xl tracking-tight text-ink"
          >
            Paper Crane
          </Link>
          <Link
            href="/home"
            className="font-sans text-xs text-graphite hover:text-ink"
          >
            Skip setup →
          </Link>
        </header>

        <ProgressBar current={currentStep} />

        <main id="main-content" tabIndex={-1} className="flex-1">{children}</main>

        <footer className="text-center font-sans text-[0.66rem] text-graphite-soft">
          Under 5 minutes from here to your first design
        </footer>
      </div>
    </div>
  );
}
