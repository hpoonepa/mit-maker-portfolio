import type { Metadata } from "next";
import BetaSignupForm from "@/components/beta/BetaSignupForm";

export const metadata: Metadata = {
  title: "Beta Access — Paper Crane",
  description:
    "Request early access to Paper Crane. We're onboarding labs in small cohorts.",
};

export default function BetaPage() {
  return (
    <main className="min-h-screen bg-paper text-ink py-24 sm:py-32">
      <div className="mx-auto w-full max-w-xl px-6">
        <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-ink/50 mb-6">
          Paper Crane · Beta
        </p>
        <h1 className="font-serif text-4xl sm:text-5xl leading-[1.05] text-ink mb-6">
          Request access.
        </h1>
        <p className="font-sans text-base text-ink/70 mb-12 max-w-md">
          We&apos;re onboarding a small cohort of labs designing real binders
          against real targets. Tell us a little about your work.
        </p>

        <div className="border-t border-ink/15 pt-10">
          <BetaSignupForm />
        </div>
      </div>
    </main>
  );
}
