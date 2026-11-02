"use client";

import { useEffect, useState } from "react";
import {
  acceptAll,
  acceptEssentialOnly,
  clearConsent,
  getConsent,
  setConsent,
  type ConsentState,
} from "@/lib/cookies";

/**
 * User-facing settings panel for managing cookie/analytics consent.
 * Mounted on /privacy-choices and reachable from the footer.
 */
export function PrivacyChoices() {
  const [state, setState] = useState<ConsentState | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setState(getConsent());
    setHydrated(true);
  }, []);

  const updateAnalytics = (next: boolean) => {
    const result = setConsent(
      { analytics: next, preferences: state?.categories.preferences ?? true },
      "custom",
    );
    setState(result);
  };

  const updatePreferences = (next: boolean) => {
    const result = setConsent(
      { analytics: state?.categories.analytics ?? false, preferences: next },
      "custom",
    );
    setState(result);
  };

  const reset = () => {
    clearConsent();
    setState(null);
  };

  return (
    <div className="space-y-8">
      <div className="rounded-xl border border-ink/10 bg-paper/60 p-5 sm:p-6">
        <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-graphite">
          Status
        </div>
        <div className="mt-2 text-[15px] text-ink/90">
          {!hydrated && "Loading your preferences..."}
          {hydrated && !state && (
            <>You haven&apos;t decided yet. The cookie banner will ask on your next visit.</>
          )}
          {hydrated && state && (
            <>
              Last decision:{" "}
              <span className="font-mono text-[12px]">
                {new Date(state.decidedAt).toLocaleString()}
              </span>{" "}
              · expires{" "}
              <span className="font-mono text-[12px]">
                {new Date(state.expiresAt).toLocaleDateString()}
              </span>
            </>
          )}
        </div>
      </div>

      <ChoiceRow
        title="Strictly necessary"
        body="Sign-in, CSRF protection, session cookies, and the record of your cookie choice. Required to use the Service. Cannot be turned off."
        checked
        disabled
        onChange={() => {}}
      />
      <ChoiceRow
        title="Privacy-friendly analytics"
        body="Plausible Analytics. Cookieless. No personal information, no cross-site tracking. Helps us see which pages people read so we can prioritize work."
        checked={state?.categories.analytics ?? false}
        disabled={!hydrated}
        onChange={updateAnalytics}
      />
      <ChoiceRow
        title="Preferences"
        body="Local storage of your theme (light/dark) and which in-app banners you've dismissed. Stored on your device only."
        checked={state?.categories.preferences ?? true}
        disabled={!hydrated}
        onChange={updatePreferences}
      />

      <div className="flex flex-wrap gap-3 pt-2">
        <button
          type="button"
          onClick={() => {
            acceptAll();
            setState(getConsent());
          }}
          className="rounded-md bg-ink px-4 py-2 text-[13px] font-medium text-paper hover:bg-crane-deep transition-colors"
        >
          Accept all
        </button>
        <button
          type="button"
          onClick={() => {
            acceptEssentialOnly();
            setState(getConsent());
          }}
          className="rounded-md border border-ink/15 px-4 py-2 text-[13px] font-medium text-ink hover:bg-ink/5 transition-colors"
        >
          Essential only
        </button>
        <button
          type="button"
          onClick={reset}
          className="rounded-md border border-ink/10 px-4 py-2 text-[13px] font-medium text-graphite hover:text-ink hover:bg-ink/5 transition-colors"
        >
          Clear my decision
        </button>
      </div>
    </div>
  );
}

function ChoiceRow({
  title,
  body,
  checked,
  disabled,
  onChange,
}: {
  title: string;
  body: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-6 rounded-xl border border-ink/10 bg-paper/60 p-5 sm:p-6">
      <div className="flex-1">
        <div className="font-display text-[18px] text-ink">{title}</div>
        <p className="mt-2 max-w-xl text-[14px] leading-relaxed text-graphite">
          {body}
        </p>
      </div>
      <label className="inline-flex shrink-0 cursor-pointer items-center gap-2 select-none">
        <span className="font-mono text-[10px] tracking-[0.22em] uppercase text-graphite">
          {checked ? "ON" : "OFF"}
        </span>
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 accent-crane-deep"
        />
      </label>
    </div>
  );
}
