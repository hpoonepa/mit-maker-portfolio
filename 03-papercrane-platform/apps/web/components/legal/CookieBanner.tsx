"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  acceptAll,
  acceptEssentialOnly,
  hasDecided,
  onConsentChange,
} from "@/lib/cookies";

/**
 * Bottom-fixed cookie banner.
 *
 * Behavior:
 *  - Hidden during SSR; only renders after we've confirmed the user has not
 *    yet decided (avoids hydration flash + content shift).
 *  - "Accept all" enables analytics; "Essential only" disables it.
 *  - After a decision is recorded, the banner unmounts and stays gone for
 *    1 year (or until the schema bumps).
 *  - Re-management lives at /privacy-choices (linked here and in the footer).
 */
export function CookieBanner() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    // Defer to next tick so we don't fight hydration.
    const t = window.setTimeout(() => {
      if (!hasDecided()) setShow(true);
    }, 50);
    const off = onConsentChange((state) => {
      if (state) setShow(false);
    });
    return () => {
      window.clearTimeout(t);
      off();
    };
  }, []);

  if (!show) return null;

  const handleAcceptAll = () => {
    acceptAll();
    setShow(false);
  };
  const handleEssential = () => {
    acceptEssentialOnly();
    setShow(false);
  };

  return (
    <div
      role="dialog"
      aria-live="polite"
      aria-label="Cookie preferences"
      className="fixed inset-x-0 bottom-0 z-[60] px-3 pb-3 sm:px-4 sm:pb-4"
    >
      <div className="mx-auto max-w-5xl rounded-xl border border-ink/10 bg-paper/95 backdrop-blur-md shadow-[0_8px_32px_rgba(0,0,0,0.08)]">
        <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:gap-6 sm:p-5">
          <div className="flex-1 text-[13px] leading-relaxed text-ink/85 sm:text-[14px]">
            <span className="font-mono text-[10px] tracking-[0.22em] uppercase text-graphite mr-2">
              Cookies
            </span>
            We use essential cookies for sign-in and a privacy-friendly
            analytics ping (Plausible, no PII, no cross-site tracking). No
            ads, no third-party trackers.{" "}
            <Link
              href="/cookie-policy"
              className="underline decoration-crane-deep/40 underline-offset-4 hover:text-ink"
            >
              Cookie policy
            </Link>
            .
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
            <button
              type="button"
              onClick={handleEssential}
              className="rounded-md border border-ink/15 bg-transparent px-3.5 py-2 text-[13px] font-medium text-ink hover:bg-ink/5 transition-colors"
            >
              Essential only
            </button>
            <button
              type="button"
              onClick={handleAcceptAll}
              className="rounded-md bg-ink px-3.5 py-2 text-[13px] font-medium text-paper hover:bg-crane-deep transition-colors"
            >
              Accept all
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
