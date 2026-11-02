"use client";
import { betaGateEnabled } from "@papercrane/types";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { AuthLayout } from "@/components/auth/AuthLayout";
import { OAuthButtons } from "@/components/auth/OAuthButtons";
import { InviteCodeGate } from "@/components/beta/InviteCodeGate";
import { createSupabaseBrowserClient } from "@/lib/supabase/client";

/**
 * Same autofill-safe field handler used in /login. Browsers (Chrome/Safari)
 * sometimes dispatch `input` without `change`, leaving controlled state
 * stale and submit buttons stuck disabled: bind to both events.
 */
function handleField(setter: (v: string) => void) {
  return (e: React.SyntheticEvent<HTMLInputElement>) =>
    setter((e.target as HTMLInputElement).value);
}

function supabaseConfigured(): boolean {
  return Boolean(
    process.env.NEXT_PUBLIC_SUPABASE_URL &&
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  );
}

/**
 * Signup screen: email + password + optional org name + ToS.
 *
 * Flow:
 *   1. POST credentials to Supabase (`signUp`)
 *   2. Stash the org name in `localStorage` keyed under `papercrane.pending-org`.
 *      The onboarding wizard reads this on first dashboard visit and pre-fills
 *      the create-org step. Avoids needing an authed RPC on the signup screen.
 *   3. Redirect to `/signup/check-email?email=…` so the user knows to verify.
 *
 * Wave 10's onboarding flow is left untouched: we only feed it the org name.
 */
function SignupForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirectTo = searchParams.get("redirectTo") ?? "/app";
  const errorParam = searchParams.get("error");
  const inviteParam = searchParams.get("invite") ?? "";
  const configured = supabaseConfigured();
  const betaGate = betaGateEnabled(process.env.NEXT_PUBLIC_BETA_GATE);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [orgName, setOrgName] = useState("");
  const [acceptedTos, setAcceptedTos] = useState(false);
  // When the gate is off we treat every submission as having a "valid"
  // invite so the rest of the form logic stays uniform.
  const [inviteValid, setInviteValid] = useState(!betaGate);
  const [inviteCode, setInviteCode] = useState("");
  const emailRef = useRef<HTMLInputElement | null>(null);
  const passwordRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const e = emailRef.current?.value ?? "";
    const p = passwordRef.current?.value ?? "";
    if (e && !email) setEmail(e);
    if (p && !password) setPassword(p);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [status, setStatus] = useState<
    | { kind: "idle" }
    | { kind: "loading" }
    | { kind: "error"; message: string }
  >(errorParam ? { kind: "error", message: errorParam } : { kind: "idle" });

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    const submitEmail = (email || emailRef.current?.value || "").trim();
    const submitPw = password || passwordRef.current?.value || "";
    if (!submitEmail || !submitPw || !acceptedTos) return;

    if (betaGate && !inviteValid) {
      setStatus({
        kind: "error",
        message: "Enter a valid invite code to continue.",
      });
      return;
    }

    if (submitPw.length < 8) {
      setStatus({
        kind: "error",
        message: "Password must be at least 8 characters.",
      });
      return;
    }

    if (!configured) {
      setStatus({
        kind: "error",
        message:
          "Sign-up is unavailable in this environment. Please try again later.",
      });
      return;
    }

    setStatus({ kind: "loading" });
    const supabase = createSupabaseBrowserClient();
    const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? window.location.origin;
    // Stash the invite code in user_metadata so the auth callback can
    // call `beta.claimInvite` once Supabase confirms the new user. We
    // never log it.
    const userMetadata: Record<string, string> = {};
    if (orgName.trim()) userMetadata.pending_org_name = orgName.trim();
    if (betaGate && inviteCode) userMetadata.beta_invite_code = inviteCode;

    const { error } = await supabase.auth.signUp({
      email: submitEmail,
      password: submitPw,
      options: {
        emailRedirectTo: `${appUrl}/auth/callback?redirectTo=${encodeURIComponent(redirectTo)}`,
        data: Object.keys(userMetadata).length > 0 ? userMetadata : undefined,
      },
    });

    if (error) {
      setStatus({ kind: "error", message: error.message });
      return;
    }

    // Pre-seed the onboarding wizard with the org name. Wave 10's flow
    // checks for this key and populates the create-org step automatically.
    if (typeof window !== "undefined" && orgName.trim()) {
      try {
        window.localStorage.setItem(
          "papercrane.pending-org",
          JSON.stringify({ name: orgName.trim() })
        );
      } catch {
        // Quota / disabled storage: non-fatal; user can still type the
        // name during onboarding.
      }
    }

    router.push(`/signup/check-email?email=${encodeURIComponent(submitEmail)}`);
  };

  const stashPendingOrg = () => {
    if (orgName.trim() && typeof window !== "undefined") {
      try {
        window.localStorage.setItem(
          "papercrane.pending-org",
          JSON.stringify({ name: orgName.trim() })
        );
      } catch {
        // Quota / disabled storage: non-fatal; user can still type the
        // name during onboarding.
      }
    }
  };

  const submitDisabled =
    status.kind === "loading" ||
    !email?.trim() ||
    !password?.trim() ||
    !acceptedTos ||
    !configured ||
    (betaGate && !inviteValid);

  return (
    <AuthLayout
      title={betaGate ? "Join the private beta" : "Create your account"}
      subtitle={
        betaGate
          ? "Paper Crane is invite-only right now. Enter your code to continue."
          : "Set up your workspace to run tools and save results."
      }
      footer={
        <>
          Already have an account?{" "}
          <Link
            href="/login"
            className="text-ink underline decoration-lattice-strong underline-offset-2 hover:decoration-ink"
          >
            Sign in →
          </Link>
        </>
      }
    >
      {!configured && (
        <p className="mb-5 rounded-xl bg-paper-fold px-4 py-3 font-sans text-[13px] text-ink">
          Sign-up is unavailable in this environment. Please try again later.
        </p>
      )}

      <InviteCodeGate
        initialCode={inviteParam || undefined}
        onValid={(c) => {
          setInviteValid(true);
          setInviteCode(c);
        }}
        onInvalid={() => {
          setInviteValid(false);
          setInviteCode("");
        }}
      >
        <OAuthButtons
          redirectTo={redirectTo}
          inviteCode={betaGate ? inviteCode : undefined}
          disabled={status.kind === "loading" || !configured}
          onError={(message) => setStatus({ kind: "error", message })}
          onBeforeRedirect={() => stashPendingOrg()}
          testIdPrefix="signup-oauth"
        />

        <div className="my-6 flex items-center gap-3">
          <div className="h-px flex-1 bg-lattice" />
          <span className="font-sans text-[12px] text-graphite-soft">
            Or continue with email
          </span>
          <div className="h-px flex-1 bg-lattice" />
        </div>

      <form onSubmit={handleSignup} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1.5">
          <span className="font-sans text-[12px] text-graphite-soft">
            Email
          </span>
          <input
            ref={emailRef}
            type="email"
            required
            autoComplete="email"
            placeholder="you@lab.edu"
            value={email}
            onChange={handleField(setEmail)}
            onInput={handleField(setEmail)}
            data-testid="signup-email"
            className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[15px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
          />
        </label>

        <label htmlFor="signup-password-input" className="flex flex-col gap-1.5">
          <span className="font-sans text-[12px] text-graphite-soft">
            Password
          </span>
          <div className="relative">
            <input
              id="signup-password-input"
              ref={passwordRef}
              type={showPassword ? "text" : "password"}
              required
              minLength={8}
              autoComplete="new-password"
              placeholder="••••••••"
              value={password}
              onChange={handleField(setPassword)}
              onInput={handleField(setPassword)}
              data-testid="signup-password"
              aria-describedby="signup-password-help"
              className="w-full rounded-xl border border-lattice-strong bg-paper px-4 py-3 pr-14 font-sans text-[15px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-pressed={showPassword}
              aria-label={showPassword ? "Hide password" : "Show password"}
              className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md px-2 py-1 font-sans text-[12px] text-graphite-soft hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane-deep"
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </div>
          {/* Live, non-blocking length feedback. Origami "fold" line: empty
              while idle, fills with a thin crane-red bar until the threshold,
              then collapses into a quiet confirmation. */}
          <div
            id="signup-password-help"
            className="flex items-center gap-2"
            aria-live="polite"
          >
            <div className="h-px flex-1 bg-lattice" aria-hidden="true">
              <div
                className={`h-px transition-all ${password.length >= 8 ? "bg-ink" : "bg-crane"}`}
                style={{ width: `${Math.min(100, (password.length / 8) * 100)}%` }}
              />
            </div>
            <span
              className={`font-sans text-[12px] ${password.length >= 8 ? "text-graphite-soft" : "text-graphite"}`}
            >
              {password.length === 0
                ? "8+ characters"
                : password.length >= 8
                  ? "Minimum length met"
                  : `${password.length}/8`}
            </span>
          </div>
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="font-sans text-[12px] text-graphite-soft">
            Organization name
            <span className="ml-1 normal-case tracking-normal text-graphite-soft">
              (optional)
            </span>
          </span>
          <input
            type="text"
            autoComplete="organization"
            placeholder="My Lab"
            value={orgName}
            onChange={handleField(setOrgName)}
            onInput={handleField(setOrgName)}
            data-testid="signup-org"
            className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[15px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
          />
          <span className="font-sans text-[12px] text-graphite-soft">
            You can rename or invite teammates later.
          </span>
        </label>

        <label className="mt-2 flex items-start gap-2.5 font-sans text-[13px] text-graphite">
          <input
            type="checkbox"
            checked={acceptedTos}
            onChange={(e) => setAcceptedTos(e.target.checked)}
            data-testid="signup-tos"
            aria-label="I agree to the Terms and Privacy Policy"
            className="mt-0.5 h-4 w-4 rounded border-lattice-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane-deep"
          />
          <span>
            I agree to the{" "}
            <a
              href="https://papercrane.bio/terms"
              target="_blank"
              rel="noopener noreferrer"
              className="text-ink underline decoration-lattice-strong underline-offset-2"
            >
              Terms
            </a>{" "}
            and{" "}
            <a
              href="https://papercrane.bio/privacy"
              target="_blank"
              rel="noopener noreferrer"
              className="text-ink underline decoration-lattice-strong underline-offset-2"
            >
              Privacy Policy
            </a>
            .
          </span>
        </label>

        <button
          type="submit"
          disabled={submitDisabled}
          data-testid="signup-submit"
          className="btn-primary justify-center disabled:opacity-60"
        >
          {status.kind === "loading" ? "Creating account…" : "Create account"}
        </button>
        </form>

        {status.kind === "error" && (
          <p className="mt-5 rounded-xl bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep">
            {status.message}
          </p>
        )}
      </InviteCodeGate>
    </AuthLayout>
  );
}

export default function SignupPage() {
  return (
    <Suspense fallback={null}>
      <SignupForm />
    </Suspense>
  );
}
