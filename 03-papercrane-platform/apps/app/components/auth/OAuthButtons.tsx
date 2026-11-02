"use client";

import { useEffect, useState } from "react";
import {
  getOAuthProviderAvailability,
  signInWithProvider,
  type OAuthProvider,
  type OAuthProviderAvailability,
} from "@/lib/supabase/oauth";

interface OAuthButtonsProps {
  /** Path to redirect to after the callback succeeds. Defaults to `/app`. */
  redirectTo?: string;
  /** Validated private-beta invite carried through an OAuth redirect. */
  inviteCode?: string;
  /** Disable the buttons (e.g. while another auth flow is loading). */
  disabled?: boolean;
  /** Show GitHub alongside Google. Defaults to false (Google-only). */
  showGitHub?: boolean;
  /**
   * Optional callback for the parent to surface the error in its own banner.
   * If omitted we render the error inline below the buttons.
   */
  onError?: (message: string) => void;
  /**
   * Optional pre-flight hook fired before redirecting. Use this to stash
   * pending org names / analytics events. Throwing will abort the OAuth call.
   */
  onBeforeRedirect?: (provider: OAuthProvider) => void;
  /** Test id prefix for E2E selectors. */
  testIdPrefix?: string;
}

/**
 * Reusable "Continue with <Provider>" button row.
 *
 * Used on /login and /signup. Mirrors the visual language already used inline
 * on those pages (rounded-full, lattice border, paper bg) so swapping in the
 * component is purely a refactor: no UX shift.
 */
export function OAuthButtons({
  redirectTo = "/app",
  inviteCode,
  disabled = false,
  showGitHub = false,
  onError,
  onBeforeRedirect,
  testIdPrefix = "oauth",
}: OAuthButtonsProps) {
  const [loading, setLoading] = useState<OAuthProvider | null>(null);
  const [inlineError, setInlineError] = useState<string | null>(null);
  const [availability, setAvailability] =
    useState<OAuthProviderAvailability | null>(null);

  useEffect(() => {
    let active = true;
    getOAuthProviderAvailability()
      .then((result) => {
        if (active) setAvailability(result);
      })
      .catch(() => {
        if (active) setAvailability({ google: false, github: false });
      });
    return () => {
      active = false;
    };
  }, []);

  const handle = async (provider: OAuthProvider) => {
    setInlineError(null);
    try {
      onBeforeRedirect?.(provider);
    } catch {
      // Pre-flight hook decided to abort: surface nothing.
      return;
    }
    setLoading(provider);
    const result = await signInWithProvider(provider, redirectTo, inviteCode);
    if (!result.ok) {
      const message = result.error ?? "OAuth sign-in failed.";
      if (onError) onError(message);
      else setInlineError(message);
      setLoading(null);
      return;
    }
    // On success the browser navigates away; keep the spinner state until then.
  };

  const buttonClass =
    "flex w-full items-center justify-center gap-3 rounded-full border border-lattice-strong bg-paper px-5 py-3 font-sans text-[14px] text-ink transition-colors hover:bg-paper-fold disabled:opacity-60";

  return (
    <div className="flex flex-col gap-3">
      <button
        type="button"
        onClick={() => handle("google")}
        disabled={disabled || loading !== null || availability?.google !== true}
        data-testid={`${testIdPrefix}-google`}
        data-provider-status={
          availability === null
            ? "checking"
            : availability.google
              ? "enabled"
              : "disabled"
        }
        className={buttonClass}
      >
        <GoogleMark className="h-4 w-4" />
        {loading === "google"
          ? "Redirecting…"
          : availability === null
            ? "Checking Google…"
            : availability.google
              ? "Continue with Google"
              : "Google sign-in unavailable"}
      </button>
      {showGitHub && (
        <button
          type="button"
          onClick={() => handle("github")}
          disabled={disabled || loading !== null || availability?.github !== true}
          data-testid={`${testIdPrefix}-github`}
          className={buttonClass}
        >
          <GitHubMark className="h-4 w-4" />
          {loading === "github" ? "Redirecting…" : "Continue with GitHub"}
        </button>
      )}
      {availability !== null && !availability.google && (
        <p className="font-sans text-[12px] text-graphite-soft">
          Google isn&apos;t enabled for this environment yet. Continue with email.
        </p>
      )}
      {inlineError && (
        <p
          role="alert"
          className="rounded-xl bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep"
        >
          {inlineError}
        </p>
      )}
    </div>
  );
}

function GoogleMark({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
        fill="#4285F4"
      />
      <path
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A10.997 10.997 0 0 0 12 23z"
        fill="#34A853"
      />
      <path
        d="M5.84 14.1a6.6 6.6 0 0 1 0-4.2V7.07H2.18a11 11 0 0 0 0 9.86l3.66-2.83z"
        fill="#FBBC05"
      />
      <path
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.83C6.71 7.31 9.14 5.38 12 5.38z"
        fill="#EA4335"
      />
    </svg>
  );
}

function GitHubMark({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" fill="#1A1A1A">
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M12 1.5C6.2 1.5 1.5 6.3 1.5 12.2c0 4.7 3 8.7 7.2 10.1.5.1.7-.2.7-.5v-1.8c-2.9.6-3.5-1.4-3.5-1.4-.5-1.2-1.1-1.5-1.1-1.5-.9-.6.1-.6.1-.6 1 .1 1.6 1.1 1.6 1.1.9 1.6 2.4 1.1 3 .9.1-.7.4-1.1.6-1.4-2.3-.3-4.7-1.2-4.7-5.2 0-1.1.4-2.1 1.1-2.8-.1-.3-.5-1.4.1-2.9 0 0 .9-.3 2.9 1.1.8-.2 1.7-.3 2.6-.3.9 0 1.8.1 2.6.3 2-1.4 2.9-1.1 2.9-1.1.6 1.5.2 2.6.1 2.9.7.7 1.1 1.7 1.1 2.8 0 4-2.4 4.9-4.7 5.2.4.3.7.9.7 1.9v2.8c0 .3.2.6.7.5 4.2-1.4 7.2-5.4 7.2-10.1C22.5 6.3 17.8 1.5 12 1.5z"
      />
    </svg>
  );
}
