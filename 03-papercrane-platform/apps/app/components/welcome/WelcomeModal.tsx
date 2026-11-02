"use client";

/**
 * First-run welcome modal: 3-slide carousel shown on the user's first
 * dashboard visit. Dismissable; once dismissed, never shown again (gated by
 * `pc.seen-welcome=v1` in localStorage via `lib/onboarding/seen`).
 *
 * Triggered on mount when the flag is unset; "Get started" routes the user
 * to the new-project flow.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { Button, Dialog } from "@papercrane/ui";
import { hasSeen, markSeen } from "../../lib/onboarding/seen";

interface Slide {
  title: string;
  body: string;
}

const SLIDES: Slide[] = [
  {
    title: "Welcome to Paper Crane",
    body: "Run protein design tools, review their outputs, and keep related work in one workspace.",
  },
  {
    title: "Set up a run",
    body: "Add a target, choose a supported tool, and submit a job. Results stay attached to the project.",
  },
  {
    title: "Free plan",
    body: "The free plan includes 500 designs and does not require a credit card. You can review usage at any time.",
  },
];

export interface WelcomeModalProps {
  /** Force-open the modal regardless of localStorage (used in tests / settings). */
  forceOpen?: boolean;
  /** Where "Get started" routes to. Defaults to `/projects/new`. */
  startHref?: string;
}

export function WelcomeModal({
  forceOpen,
  startHref = "/projects/new",
}: WelcomeModalProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [slide, setSlide] = useState(0);

  // Decide whether to show on mount. We do this in an effect so the initial
  // render is deterministic between server and client (no hydration jitter).
  useEffect(() => {
    if (forceOpen) {
      setOpen(true);
      return;
    }
    if (!hasSeen("welcome")) {
      setOpen(true);
    }
  }, [forceOpen]);

  function dismiss() {
    markSeen("welcome");
    setOpen(false);
  }

  function getStarted() {
    dismiss();
    router.push(startHref);
  }

  const isLast = slide === SLIDES.length - 1;
  const current = SLIDES[slide]!;

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) dismiss();
      }}
      hideClose
      size="md"
      aria-label="Welcome to Paper Crane"
    >
      <div className="px-2 py-4">
        <p className="mb-3 font-sans text-[12px] text-graphite-soft">
          {slide + 1} of {SLIDES.length}
        </p>
        <h2 className="mb-2 font-display text-xl font-semibold tracking-tight text-ink">
          {current.title}
        </h2>
        <p className="text-sm text-graphite-soft max-w-sm leading-relaxed">
          {current.body}
        </p>

        <div
          className="mt-5 flex items-center gap-1.5"
          role="tablist"
          aria-label="Welcome slides"
        >
          {SLIDES.map((_, i) => (
            <button
              key={i}
              type="button"
              role="tab"
              aria-selected={i === slide}
              aria-label={`Slide ${i + 1}`}
              onClick={() => setSlide(i)}
              className={
                "h-1.5 w-8 rounded-sm transition-colors " +
                (i === slide
                  ? "bg-crane"
                  : "bg-lattice hover:bg-lattice-strong")
              }
            />
          ))}
        </div>

        <div className="mt-6 flex w-full items-center justify-between gap-3">
          <Button variant="ghost" size="sm" onClick={dismiss}>
            Skip
          </Button>
          {isLast ? (
            <Button
              variant="primary"
              size="md"
              onClick={getStarted}
              rightIcon={<ArrowRight className="h-4 w-4" />}
            >
              Get started
            </Button>
          ) : (
            <Button
              variant="primary"
              size="md"
              onClick={() =>
                setSlide((s) => Math.min(s + 1, SLIDES.length - 1))
              }
              rightIcon={<ArrowRight className="h-4 w-4" />}
            >
              Next
            </Button>
          )}
        </div>
      </div>
    </Dialog>
  );
}
