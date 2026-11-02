"use client";

import Link from "next/link";
import { CraneMark } from "@/components/brand/CraneMark";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { OAuthButtons } from "@/components/auth/OAuthButtons";
import { createSupabaseBrowserClient } from "@/lib/supabase/client";

/**
 * Handler factory that updates a setter from either React `onChange` or the
 * native `onInput` event. Some password managers / browser autofill flows
 * dispatch `input` without triggering React's synthetic `change`, which leaves
 * controlled inputs out of sync and the Submit button stuck disabled.
 */
function handleField(setter: (v: string) => void) {
  return (e: React.SyntheticEvent<HTMLInputElement>) =>
    setter((e.target as HTMLInputElement).value);
}

/**
 * Dev-safe check for Supabase env. When missing (local preview / landing-only
 * dev), we render a "not configured" placeholder instead of calling the
 * client (which throws) or crashing the page. Production always has these
 * set via the deploy env, so this branch is never taken in prod.
 */
function supabaseConfigured(): boolean {
  return Boolean(
    process.env.NEXT_PUBLIC_SUPABASE_URL &&
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  );
}

/**
 * Login screen: Supabase email OTP + Google OAuth.
 *
 * We avoid @supabase/auth-ui-react to keep styling consistent with the
 * landing tokens. It's two inputs + two buttons; no need for the library.
 */
function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirectTo = searchParams.get("redirectTo") ?? "/dashboard";
  const errorParam = searchParams.get("error");
  const configured = supabaseConfigured();
  const showDevHint = process.env.NEXT_PUBLIC_DEV_HINT === "true";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"password" | "magic">("password");
  const emailRef = useRef<HTMLInputElement | null>(null);
  const passwordRef = useRef<HTMLInputElement | null>(null);

  // Pull initial values from the DOM on mount. Browsers (Chrome/Safari) may
  // autofill credentials before React hydrates, which leaves our controlled
  // state empty and the Submit button stuck disabled. Sync once after mount.
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
    | { kind: "magic-sent"; email: string }
    | { kind: "error"; message: string }
  >(errorParam ? { kind: "error", message: errorParam } : { kind: "idle" });

  const handlePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    // Re-read from refs at submit time: covers the rare case where autofill
    // populated the DOM but the React state hasn't caught up yet.
    const submitEmail = (email || emailRef.current?.value || "").trim();
    const submitPw = password || passwordRef.current?.value || "";
    if (!submitEmail || !submitPw) return;
    if (!configured) {
      setStatus({
        kind: "error",
        message:
          "Sign-in is unavailable in this environment. Please try again later.",
      });
      return;
    }
    setStatus({ kind: "loading" });
    const supabase = createSupabaseBrowserClient();
    const { error } = await supabase.auth.signInWithPassword({
      email: submitEmail,
      password: submitPw,
    });
    if (error) {
      setStatus({ kind: "error", message: error.message });
      return;
    }
    // Middleware will resolve the user; just push to the target. RSC pages
    // re-validate via getUser() so cookies need to flush before the route
    // change: router.replace + router.refresh() does the trick.
    router.replace(redirectTo);
    router.refresh();
  };

  const handleMagic = async (e: React.FormEvent) => {
    e.preventDefault();
    const submitEmail = (email || emailRef.current?.value || "").trim();
    if (!submitEmail) return;
    if (!configured) {
      setStatus({
        kind: "error",
        message:
          "Sign-in is unavailable in this environment. Please try again later.",
      });
      return;
    }
    setStatus({ kind: "loading" });
    const supabase = createSupabaseBrowserClient();
    const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? window.location.origin;
    const { error } = await supabase.auth.signInWithOtp({
      email: submitEmail,
      options: {
        emailRedirectTo: `${appUrl}/auth/callback?redirectTo=${encodeURIComponent(redirectTo)}`,
      },
    });
    if (error) {
      setStatus({ kind: "error", message: error.message });
      return;
    }
    setStatus({ kind: "magic-sent", email: submitEmail });
  };

  return (
    <div className="w-full max-w-md">
      <Link
        href="/"
        className="inline-flex items-center gap-2 font-sans font-medium text-[18px] lowercase tracking-[-0.02em] text-ink"
      >
        <CraneMark className="w-8 h-8 text-crane" />
        papercrane
      </Link>

      <h1 className="mt-8 sm:mt-10 font-sans font-medium text-3xl sm:text-display-md text-ink">
        Sign in
      </h1>

      <div className="mt-8">
        {!configured && (
          <p className="mb-5 rounded-xl bg-paper-fold px-4 py-3 font-sans text-[13px] text-ink">
            Sign-in is unavailable in this environment. Please try again later.
          </p>
        )}
        {showDevHint && configured && (
          <p className="mb-5 rounded-xl bg-paper-fold px-4 py-3 font-sans text-[12px] text-ink">
            <span className="font-sans tabular-nums text-[12px] text-graphite-soft">
              Dev demo
            </span>
            <br />
            Email{" "}
            <code className="font-sans tabular-nums text-[12px]">demo@papercrane.bio</code>
            <br />
            Password is in{" "}
            <code className="font-sans tabular-nums text-[12px]">
              .agent-logs/20-demo-creds.txt
            </code>
            .
          </p>
        )}
        <OAuthButtons
          redirectTo={redirectTo}
          disabled={status.kind === "loading" || !configured}
          onError={(message) => setStatus({ kind: "error", message })}
          testIdPrefix="e2e-signup"
        />

        <div className="my-6 flex items-center gap-3">
          <div className="h-px flex-1 bg-lattice" />
          <span className="font-sans text-[12px] text-graphite-soft">
            Or continue with email
          </span>
          <div className="h-px flex-1 bg-lattice" />
        </div>

        <div className="mb-4 flex items-center gap-1 rounded-full border border-lattice bg-paper-fold p-1 font-sans text-[12px]">
          <button
            type="button"
            onClick={() => setMode("password")}
            aria-pressed={mode === "password"}
            className={
              mode === "password"
                ? "flex-1 rounded-full bg-paper px-3 py-1.5 text-ink shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane-deep"
                : "flex-1 rounded-full px-3 py-1.5 text-graphite hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane-deep"
            }
          >
            Password
          </button>
          <button
            type="button"
            onClick={() => setMode("magic")}
            aria-pressed={mode === "magic"}
            className={
              mode === "magic"
                ? "flex-1 rounded-full bg-paper px-3 py-1.5 text-ink shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane-deep"
                : "flex-1 rounded-full px-3 py-1.5 text-graphite hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane-deep"
            }
          >
            Magic link
          </button>
        </div>

        <form
          onSubmit={mode === "password" ? handlePassword : handleMagic}
          className="flex flex-col gap-3"
        >
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
              data-testid="e2e-signup-email"
              className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[15px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
            />
          </label>
          {mode === "password" && (
            <label className="flex flex-col gap-1.5">
              <span className="font-sans text-[12px] text-graphite-soft">
                Password
              </span>
              <input
                ref={passwordRef}
                type="password"
                required
                autoComplete="current-password"
                placeholder="••••••••"
                value={password}
                onChange={handleField(setPassword)}
                onInput={handleField(setPassword)}
                data-testid="e2e-signup-password"
                className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[15px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
              />
            </label>
          )}
          <button
            type="submit"
            disabled={
              status.kind === "loading" ||
              !email?.trim() ||
              (mode === "password" && !password?.trim()) ||
              !configured
            }
            data-testid="e2e-signup-submit"
            className="btn-primary justify-center disabled:opacity-60"
          >
            {status.kind === "loading"
              ? mode === "password"
                ? "Signing in…"
                : "Sending…"
              : mode === "password"
                ? "Sign in"
                : "Send magic link"}
          </button>
          {mode === "password" && (
            <Link
              href="/forgot-password"
              className="self-end font-sans text-[12px] text-graphite hover:text-ink"
            >
              Forgot password?
            </Link>
          )}
        </form>

        {status.kind === "magic-sent" && (
          <p className="mt-5 rounded-xl bg-paper-fold px-4 py-3 font-sans text-[13px] text-ink">
            Check <strong>{status.email}</strong> for a sign-in link.
          </p>
        )}
        {status.kind === "error" && (
          <p className="mt-5 rounded-xl bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep">
            {status.message}
          </p>
        )}
      </div>

      <p className="mt-6 font-sans text-[13px] text-graphite">
        New to Papercrane?{" "}
        <Link
          href="/signup"
          className="text-ink underline decoration-lattice-strong underline-offset-2 hover:decoration-ink"
        >
          Create an account →
        </Link>
      </p>
    </div>
  );
}

/**
 * Render an above-the-fold skeleton synchronously so the page doesn't FCP
 * blank while `useSearchParams` suspends. Visually matches the real form so
 * the layout doesn't shift (CLS = 0) when LoginForm hydrates in.
 */
function LoginSkeleton() {
  return (
    <div className="w-full max-w-md" aria-hidden="true">
      <div className="inline-flex items-center gap-2 font-sans font-medium text-[18px] lowercase tracking-[-0.02em] text-ink">
        <CraneMark className="w-8 h-8 text-crane" />
        papercrane
      </div>
      <h1 className="mt-10 font-sans font-medium text-display-md text-ink">Sign in</h1>
      <div className="mt-8">
        <div className="h-11 rounded-full border border-lattice-strong bg-paper" />
        <div className="my-6 flex items-center gap-3">
          <div className="h-px flex-1 bg-lattice" />
          <span className="font-sans text-[12px] text-graphite-soft">
            or email
          </span>
          <div className="h-px flex-1 bg-lattice" />
        </div>
        <div className="mb-4 h-9 rounded-full border border-lattice bg-paper-fold" />
        <div className="flex flex-col gap-3">
          <div className="h-[68px] rounded-xl border border-lattice-strong bg-paper" />
          <div className="h-[68px] rounded-xl border border-lattice-strong bg-paper" />
          <div className="h-11 rounded-full bg-paper-fold" />
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginSkeleton />}>
      <LoginForm />
    </Suspense>
  );
}
