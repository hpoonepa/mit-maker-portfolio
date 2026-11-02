"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { AuthLayout } from "@/components/auth/AuthLayout";
import { createSupabaseBrowserClient } from "@/lib/supabase/client";

const COOLDOWN_SECONDS = 60;

function CheckEmailContent() {
  const params = useSearchParams();
  const email = params.get("email") ?? "";
  const [cooldown, setCooldown] = useState(0);
  const [status, setStatus] = useState<
    | { kind: "idle" }
    | { kind: "loading" }
    | { kind: "sent" }
    | { kind: "error"; message: string }
  >({ kind: "idle" });

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setInterval(() => setCooldown((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, [cooldown]);

  const onResend = async () => {
    if (!email || cooldown > 0) return;
    setStatus({ kind: "loading" });
    try {
      const supabase = createSupabaseBrowserClient();
      const appUrl =
        process.env.NEXT_PUBLIC_APP_URL ?? window.location.origin;
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: `${appUrl}/auth/callback?redirectTo=/reset-password`,
      });
      if (error) {
        setStatus({ kind: "error", message: error.message });
        return;
      }
      setStatus({ kind: "sent" });
      setCooldown(COOLDOWN_SECONDS);
    } catch (err) {
      setStatus({
        kind: "error",
        message: err instanceof Error ? err.message : "Failed to resend",
      });
    }
  };

  return (
    <AuthLayout
      title="Check your inbox"
      subtitle={
        email ? (
          <>
            If an account exists for{" "}
            <strong className="text-ink">{email}</strong>, we sent a reset
            link. Click it to choose a new password.
          </>
        ) : (
          <>
            If an account exists for that email, we sent a reset link. Click
            it to choose a new password.
          </>
        )
      }
      footer={
        <>
          <Link
            href="/login"
            className="text-ink underline decoration-lattice-strong underline-offset-2 hover:decoration-ink"
          >
            Back to sign in
          </Link>
        </>
      }
    >
      <div className="flex flex-col gap-4 font-sans text-[14px] text-graphite">
        <p>
          The link expires in 1 hour. Check spam if it doesn't show up: the
          sender is{" "}
          <code className="font-mono text-[12px]">noreply@papercrane.bio</code>
          .
        </p>

        <button
          type="button"
          onClick={onResend}
          disabled={cooldown > 0 || status.kind === "loading" || !email}
          data-testid="resend-reset"
          className="self-start rounded-full border border-lattice-strong bg-paper px-4 py-2 font-sans text-[13px] text-ink transition-colors hover:bg-paper-fold disabled:opacity-50"
        >
          {status.kind === "loading"
            ? "Sending…"
            : cooldown > 0
              ? `Resend in ${cooldown}s`
              : "Resend email"}
        </button>

        {status.kind === "sent" && (
          <p className="rounded-xl bg-paper-fold px-4 py-3 text-[13px] text-ink">
            Sent. Give it a minute to arrive.
          </p>
        )}
        {status.kind === "error" && (
          <p className="rounded-xl bg-crane-glow px-4 py-3 text-[13px] text-crane-deep">
            {status.message}
          </p>
        )}
      </div>
    </AuthLayout>
  );
}

export default function ForgotCheckEmailPage() {
  return (
    <Suspense fallback={null}>
      <CheckEmailContent />
    </Suspense>
  );
}
