"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AuthLayout } from "@/components/auth/AuthLayout";
import { createSupabaseBrowserClient } from "@/lib/supabase/client";

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
 * "Forgot password" entry. Submits to Supabase `resetPasswordForEmail`,
 * which mails a recovery link to /reset-password. We always show the same
 * confirmation screen regardless of whether the address is registered, so
 * the form can't be used as an account-existence oracle.
 */
export default function ForgotPasswordPage() {
  const router = useRouter();
  const configured = supabaseConfigured();
  const [email, setEmail] = useState("");
  const emailRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const e = emailRef.current?.value ?? "";
    if (e && !email) setEmail(e);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [status, setStatus] = useState<
    | { kind: "idle" }
    | { kind: "loading" }
    | { kind: "error"; message: string }
  >({ kind: "idle" });

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const submitEmail = (email || emailRef.current?.value || "").trim();
    if (!submitEmail) return;
    if (!configured) {
      setStatus({
        kind: "error",
        message:
          "Supabase is not configured in this environment. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.",
      });
      return;
    }
    setStatus({ kind: "loading" });
    const supabase = createSupabaseBrowserClient();
    const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? window.location.origin;
    const { error } = await supabase.auth.resetPasswordForEmail(submitEmail, {
      redirectTo: `${appUrl}/auth/callback?redirectTo=/reset-password`,
    });
    if (error) {
      // Still navigate to the confirmation screen: Supabase already returns
      // success for unknown emails, but in case of e.g. rate-limit errors we
      // surface the message inline.
      setStatus({ kind: "error", message: error.message });
      return;
    }
    router.push(
      `/forgot-password/check-email?email=${encodeURIComponent(submitEmail)}`
    );
  };

  return (
    <AuthLayout
      title="Reset your password"
      subtitle="We'll email you a link to set a new one."
      footer={
        <>
          Remembered it?{" "}
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
        <label className="flex flex-col gap-1.5">
          <span className="font-sans text-[12px] uppercase tracking-[0.14em] text-graphite-soft">
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
            data-testid="forgot-email"
            className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[15px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
          />
        </label>
        <button
          type="submit"
          disabled={
            status.kind === "loading" || !email?.trim() || !configured
          }
          data-testid="forgot-submit"
          className="btn-primary justify-center disabled:opacity-60"
        >
          {status.kind === "loading" ? "Sending…" : "Send reset link"}
        </button>
      </form>

      {status.kind === "error" && (
        <p className="mt-5 rounded-xl bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep">
          {status.message}
        </p>
      )}
    </AuthLayout>
  );
}
