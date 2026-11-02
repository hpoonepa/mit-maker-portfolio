"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { AuthLayout } from "@/components/auth/AuthLayout";
import { createSupabaseBrowserClient } from "@/lib/supabase/client";

/**
 * Reset-password screen. Reached after the user clicks the email link from
 * /forgot-password.
 *
 * The Supabase recovery flow can arrive two ways:
 *   1. PKCE: link goes to /auth/callback?code=…, which exchanges and then
 *      redirects to /reset-password with an authenticated session.
 *   2. Hash token (legacy): link goes straight here with `#access_token=…`.
 *      Supabase JS auto-parses the hash on init.
 *
 * In both cases, by the time this component mounts the browser client has
 * a "recovery" session and `auth.updateUser({ password })` will succeed.
 *
 * The `?token=` query param is supported as a fallback hint for users on
 * older email templates: we treat its presence as "we expect you to have a
 * recovery session" but don't try to consume it directly.
 */
function ResetPasswordForm() {
  const router = useRouter();
  const params = useSearchParams();
  const tokenHint = params.get("token");
  const [hasSession, setHasSession] = useState<boolean | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [status, setStatus] = useState<
    | { kind: "idle" }
    | { kind: "loading" }
    | { kind: "success" }
    | { kind: "error"; message: string }
  >({ kind: "idle" });

  // On mount, check whether Supabase JS has a session ready (recovery or
  // otherwise). If not, the user landed here cold: bounce to forgot.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const supabase = createSupabaseBrowserClient();
        const { data } = await supabase.auth.getSession();
        if (!cancelled) setHasSession(Boolean(data.session));
      } catch {
        if (!cancelled) setHasSession(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password.length < 8) {
      setStatus({
        kind: "error",
        message: "Password must be at least 8 characters.",
      });
      return;
    }
    if (password !== confirm) {
      setStatus({ kind: "error", message: "Passwords don't match." });
      return;
    }
    setStatus({ kind: "loading" });
    const supabase = createSupabaseBrowserClient();
    const { error } = await supabase.auth.updateUser({ password });
    if (error) {
      setStatus({ kind: "error", message: error.message });
      return;
    }
    setStatus({ kind: "success" });
    // Brief pause so the user sees the confirmation, then sign in.
    setTimeout(() => {
      router.replace("/app");
      router.refresh();
    }, 1200);
  };

  if (hasSession === false) {
    return (
      <AuthLayout
        title="Reset link expired"
        subtitle="This password reset link is no longer valid. Request a new one to continue."
        footer={
          <>
            Already remember it?{" "}
            <Link
              href="/login"
              className="text-ink underline decoration-lattice-strong underline-offset-2 hover:decoration-ink"
            >
              Back to sign in
            </Link>
          </>
        }
      >
        <Link
          href="/forgot-password"
          className="btn-primary w-full justify-center"
        >
          Request a new link
        </Link>
      </AuthLayout>
    );
  }

  // Live, non-blocking feedback: keep the submit button gated by these but
  // show the user *why* before they hit submit so they're not surprised.
  const lengthOk = password.length >= 8;
  const matchOk = confirm.length === 0 || password === confirm;
  const tokenSubtitle = tokenHint
    ? "Pick something strong: minimum 8 characters."
    : "Pick something strong: minimum 8 characters.";

  return (
    <AuthLayout
      title="Choose a new password"
      subtitle={tokenSubtitle}
      footer={
        <>
          Changed your mind?{" "}
          <Link
            href="/login"
            className="text-ink underline decoration-lattice-strong underline-offset-2 hover:decoration-ink"
          >
            Back to sign in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <label htmlFor="reset-password-input" className="flex flex-col gap-1.5">
          <span className="font-sans text-[12px] uppercase tracking-[0.14em] text-graphite-soft">
            New password
          </span>
          <div className="relative">
            <input
              id="reset-password-input"
              type={showPassword ? "text" : "password"}
              required
              minLength={8}
              autoComplete="new-password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              data-testid="reset-password"
              className="w-full rounded-xl border border-lattice-strong bg-paper px-4 py-3 pr-14 font-sans text-[15px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-pressed={showPassword}
              aria-label={showPassword ? "Hide password" : "Show password"}
              className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md px-2 py-1 font-sans text-[11px] uppercase tracking-[0.14em] text-graphite-soft hover:text-ink"
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </div>
          {password.length > 0 && (
            <span
              className={`font-sans text-[12px] ${lengthOk ? "text-graphite-soft" : "text-crane-deep"}`}
              aria-live="polite"
            >
              {lengthOk ? "✓ At least 8 characters" : `${password.length}/8 characters`}
            </span>
          )}
        </label>

        <label htmlFor="reset-password-confirm-input" className="flex flex-col gap-1.5">
          <span className="font-sans text-[12px] uppercase tracking-[0.14em] text-graphite-soft">
            Confirm password
          </span>
          <input
            id="reset-password-confirm-input"
            type={showPassword ? "text" : "password"}
            required
            minLength={8}
            autoComplete="new-password"
            placeholder="••••••••"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            data-testid="reset-password-confirm"
            aria-invalid={!matchOk}
            className={`rounded-xl border bg-paper px-4 py-3 font-sans text-[15px] text-ink placeholder:text-graphite-soft focus:outline-none ${
              matchOk ? "border-lattice-strong focus:border-ink" : "border-crane focus:border-crane"
            }`}
          />
          {confirm.length > 0 && !matchOk && (
            <span className="font-sans text-[12px] text-crane-deep" aria-live="polite">
              Passwords don't match
            </span>
          )}
        </label>

        <button
          type="submit"
          disabled={
            status.kind === "loading" ||
            status.kind === "success" ||
            !password ||
            !confirm ||
            hasSession !== true
          }
          data-testid="reset-submit"
          className="btn-primary justify-center disabled:opacity-60"
        >
          {status.kind === "loading"
            ? "Updating…"
            : status.kind === "success"
              ? "Updated: signing you in…"
              : "Update password"}
        </button>
      </form>

      {status.kind === "error" && (
        <p className="mt-5 rounded-xl bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep">
          {status.message}
        </p>
      )}
      {status.kind === "success" && (
        <p className="mt-5 rounded-xl bg-paper-fold px-4 py-3 font-sans text-[13px] text-ink">
          Password updated. Redirecting to your dashboard…
        </p>
      )}
    </AuthLayout>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordForm />
    </Suspense>
  );
}
