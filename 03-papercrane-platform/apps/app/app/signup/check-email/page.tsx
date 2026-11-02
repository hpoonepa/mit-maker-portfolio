"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { AuthLayout } from "@/components/auth/AuthLayout";
import { createSupabaseBrowserClient } from "@/lib/supabase/client";

const COOLDOWN_SECONDS = 60;

/**
 * Post-signup confirmation screen. Tells the user to check their inbox and
 * exposes a resend button on a 60s cooldown to deter accidental spam while
 * still letting people recover from "I didn't get the email".
 *
 * The email is passed via querystring rather than localStorage so this page
 * works after a navigation/tab-restore.
 */
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
      const { error } = await supabase.auth.resend({
        type: "signup",
        email,
        options: {
          emailRedirectTo: `${appUrl}/auth/callback?redirectTo=/app`,
        },
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
            We sent a confirmation link to{" "}
            <strong className="text-ink">{email}</strong>. Click it to finish
            setting up your account.
          </>
        ) : (
          <>We sent a confirmation link to your email. Click it to finish
          setting up your account.</>
        )
      }
      footer={
        <>
          Wrong address?{" "}
          <Link
            href="/signup"
            className="text-ink underline decoration-lattice-strong underline-offset-2 hover:decoration-ink"
          >
            Back to sign up
          </Link>
        </>
      }
    >
      <div className="flex flex-col gap-4 font-sans text-[14px] text-graphite">
        <p>
          The link expires in 1 hour. If you don't see it, check spam or junk -
          the sender is{" "}
          <code className="font-mono text-[12px]">noreply@papercrane.bio</code>
          .
        </p>

        <button
          type="button"
          onClick={onResend}
          disabled={cooldown > 0 || status.kind === "loading" || !email}
          data-testid="resend-email"
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

export default function CheckEmailPage() {
  return (
    <Suspense fallback={null}>
      <CheckEmailContent />
    </Suspense>
  );
}
