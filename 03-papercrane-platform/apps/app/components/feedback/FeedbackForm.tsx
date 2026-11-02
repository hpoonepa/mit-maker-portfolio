"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Star, X } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { useToast } from "@/components/toasts/useToast";
import {
  captureViewport,
  getRecentConsoleErrors,
  getRecentNetworkFailures,
} from "@/lib/screenshot";
import { FeedbackThanks } from "./FeedbackThanks";

const CATEGORIES: ReadonlyArray<{
  id: "bug" | "feature" | "improvement" | "praise" | "other";
  label: string;
  hint: string;
}> = [
  { id: "bug", label: "Bug", hint: "Something is broken or wrong" },
  { id: "feature", label: "Feature request", hint: "I'd love to see…" },
  {
    id: "improvement",
    label: "Improvement",
    hint: "This could work better if…",
  },
  { id: "praise", label: "Praise", hint: "Something I love" },
  { id: "other", label: "Other", hint: "Anything else" },
];

const APP_VERSION =
  // Webpack/Next inlines NEXT_PUBLIC_* env vars at build time; falls back
  // to "dev" when running unbuilt or in tests.
  (typeof process !== "undefined" &&
    (process.env.NEXT_PUBLIC_APP_VERSION as string | undefined)) ||
  "dev";

/**
 * Modal form for submitting feedback. Owns its own draft state so the
 * widget button can mount/unmount the form freely. Calls
 * `feedback.submit` and shows a thanks card + toast on success.
 */
export function FeedbackForm({
  open,
  onClose,
  userInfo,
}: {
  open: boolean;
  onClose: () => void;
  userInfo?: {
    userId?: string;
    orgSlug?: string;
    tier?: string;
  };
}) {
  const [category, setCategory] =
    useState<(typeof CATEGORIES)[number]["id"]>("bug");
  const [rating, setRating] = useState<number | null>(null);
  const [body, setBody] = useState("");
  const [includeScreenshot, setIncludeScreenshot] = useState(true);
  const [includeDiagnostics, setIncludeDiagnostics] = useState(true);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dialogRef = useRef<HTMLDivElement | null>(null);
  const { toast } = useToast();
  const submit = trpc.feedback.submit.useMutation();

  const charCount = body.trim().length;
  const charLimit = 2000;
  const charMin = 5;
  const canSubmit =
    !submit.isPending && charCount >= charMin && charCount <= charLimit;

  // Reset draft each time the modal closes so re-opening shows a blank form.
  useEffect(() => {
    if (!open) {
      const t = setTimeout(() => {
        setSubmitted(false);
        setError(null);
        setBody("");
        setRating(null);
        setCategory("bug");
        setIncludeScreenshot(true);
        setIncludeDiagnostics(true);
      }, 200);
      return () => clearTimeout(t);
    }
  }, [open]);

  // Focus trap: focus the textarea on open, and close on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const viewport =
    typeof window === "undefined"
      ? null
      : { w: window.innerWidth, h: window.innerHeight };

  if (!open) return null;

  const onSubmit = async () => {
    setError(null);
    if (!canSubmit) return;

    let screenshotKey: string | undefined;
    let screenshotSkippedReason: string | undefined;
    if (includeScreenshot) {
      const shot = await captureViewport();
      // We don't have an upload endpoint wired in this widget yet; we
      // record the data URL length and the skip reason in metadata so
      // the admin view can show "screenshot present (153 KB)" and the
      // backend can pull from a follow-up upload step later.
      if (shot.dataUrl) {
        screenshotKey = `inline:${shot.dataUrl.length}`;
      } else {
        screenshotSkippedReason = shot.skippedReason;
      }
    }

    const metadata: Record<string, unknown> = {
      app: { version: APP_VERSION },
      viewport: viewport ?? null,
      user: userInfo ?? null,
    };
    if (includeDiagnostics) {
      metadata.consoleErrors = getRecentConsoleErrors();
      metadata.networkFailures = getRecentNetworkFailures();
    }
    if (screenshotSkippedReason) {
      metadata.screenshotSkippedReason = screenshotSkippedReason;
    }

    try {
      await submit.mutateAsync({
        category,
        ...(rating !== null ? { rating } : {}),
        body: body.trim(),
        ...(typeof window !== "undefined"
          ? { pageUrl: window.location.href }
          : {}),
        ...(typeof navigator !== "undefined"
          ? { userAgent: navigator.userAgent.slice(0, 512) }
          : {}),
        ...(screenshotKey ? { screenshotKey } : {}),
        metadata,
      });
      setSubmitted(true);
      toast({
        title: "Thanks, we'll be in touch",
        variant: "success",
      });
      // Auto-close shortly after the thanks card lands.
      setTimeout(() => onClose(), 1800);
    } catch (e) {
      setError(
        (e as Error).message ?? "Could not send feedback. Please try again.",
      );
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-ink/30 sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="feedback-dialog-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      data-testid="feedback-dialog"
    >
      <div
        ref={dialogRef}
        className="w-full max-w-md rounded-t-2xl bg-paper p-5 shadow-xl sm:"
      >
        <div className="mb-3 flex items-start justify-between">
          <div>
            <h2
              id="feedback-dialog-title"
              className="font-sans text-[15px] font-medium text-ink"
            >
              Send feedback
            </h2>
            <p className="mt-0.5 font-sans text-[12px] text-ink/60">
              We read every note. Beta thanks!
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full p-1 text-ink/60 hover:bg-paper-fold/60 hover:text-ink"
            aria-label="Close feedback"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {submitted ? (
          <FeedbackThanks onClose={onClose} />
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void onSubmit();
            }}
            className="flex flex-col gap-3.5"
          >
            <fieldset className="flex flex-col gap-1.5">
              <legend className="font-sans text-[12px] font-medium text-ink/70">
                Category
              </legend>
              <div
                className="flex flex-wrap gap-1.5"
                role="radiogroup"
                aria-label="Feedback category"
              >
                {CATEGORIES.map((c) => {
                  const checked = category === c.id;
                  return (
                    <label
                      key={c.id}
                      className={
                        "cursor-pointer rounded-full border px-3 py-1 font-sans text-[12px] " +
                        (checked
                          ? "border-ink bg-ink text-paper"
                          : "border-lattice text-ink hover:bg-paper-fold/50")
                      }
                    >
                      <input
                        type="radio"
                        name="feedback-category"
                        value={c.id}
                        checked={checked}
                        onChange={() => setCategory(c.id)}
                        className="sr-only"
                        aria-label={`${c.label}: ${c.hint}`}
                      />
                      {c.label}
                    </label>
                  );
                })}
              </div>
            </fieldset>

            <fieldset className="flex items-center gap-2">
              <legend className="sr-only">Rating</legend>
              <span className="font-sans text-[12px] font-medium text-ink/70">
                Rating
              </span>
              <div className="flex items-center gap-0.5">
                {[1, 2, 3, 4, 5].map((n) => {
                  const active = rating !== null && n <= rating;
                  return (
                    <button
                      key={n}
                      type="button"
                      aria-label={`${n} star${n > 1 ? "s" : ""}`}
                      aria-pressed={active}
                      onClick={() => setRating(rating === n ? null : n)}
                      className="rounded p-0.5 hover:bg-paper-fold/60"
                    >
                      <Star
                        className={
                          "h-4 w-4 " +
                          (active
                            ? "fill-amber-400 text-amber-500"
                            : "text-ink/40")
                        }
                      />
                    </button>
                  );
                })}
              </div>
            </fieldset>

            <label className="flex flex-col gap-1.5">
              <span className="font-sans text-[12px] font-medium text-ink/70">
                What&apos;s on your mind?
              </span>
              <textarea
                required
                minLength={charMin}
                maxLength={charLimit}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder="Steps to reproduce, what you'd love to see, or anything else…"
                rows={5}
                className="resize-none rounded-lg border border-lattice bg-paper px-3 py-2 font-sans text-[13px] text-ink placeholder:text-ink/40 focus:border-ink focus:outline-none"
                data-testid="feedback-body"
                autoFocus
              />
              <span
                className={
                  "self-end font-mono text-[10.5px] " +
                  (charCount > charLimit
                    ? "text-red-600"
                    : charCount < charMin
                      ? "text-ink/40"
                      : "text-ink/60")
                }
              >
                {charCount}/{charLimit}
              </span>
            </label>

            <div className="flex flex-col gap-1.5 rounded-lg bg-paper-fold/40 px-3 py-2">
              <label className="flex items-center gap-2 font-sans text-[12px] text-ink/80">
                <input
                  type="checkbox"
                  checked={includeScreenshot}
                  onChange={(e) => setIncludeScreenshot(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-lattice"
                />
                Include screenshot of this page
              </label>
              <label className="flex items-center gap-2 font-sans text-[12px] text-ink/80">
                <input
                  type="checkbox"
                  checked={includeDiagnostics}
                  onChange={(e) => setIncludeDiagnostics(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-lattice"
                />
                Include recent console errors and network failures
              </label>
            </div>

            {error && (
              <p
                className="font-sans text-[12px] text-red-600"
                role="alert"
                data-testid="feedback-error"
              >
                {error}
              </p>
            )}

            <div className="mt-1 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-full border border-lattice px-4 py-1.5 font-sans text-[12.5px] text-ink hover:bg-paper-fold/50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!canSubmit}
                className="inline-flex items-center gap-2 rounded-full bg-ink px-4 py-1.5 font-sans text-[12.5px] text-paper hover:bg-ink/90 disabled:opacity-50"
                data-testid="feedback-submit"
              >
                {submit.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : null}
                Send feedback
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
