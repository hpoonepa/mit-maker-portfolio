"use client";

import { useEffect, useState } from "react";
import { trpc } from "@/lib/trpc/client";
import { betaGateEnabled } from "@papercrane/types";

/**
 * Pre-signup gate. Wraps an inner form (or any children) with an invite-
 * code check. While `NEXT_PUBLIC_BETA_GATE === 'true'`, the children are
 * hidden until the caller types a valid PC-XXXX-XXXX code; the validated
 * code is mirrored to the parent through `onValid` so the signup form
 * can submit it alongside email/password.
 *
 * The gate itself is *never* the source of truth for whether a user
 * actually got access: we re-check on the server inside `claimInvite`,
 * which is the only place that increments `usedCount`. A user who
 * disables the gate via DevTools still cannot create an account because
 * the auth callback refuses to mark onboarding complete without a
 * successful claim.
 */
export function InviteCodeGate({
  initialCode,
  onValid,
  onInvalid,
  children,
}: {
  initialCode?: string;
  onValid: (code: string) => void;
  onInvalid: () => void;
  children: React.ReactNode;
}) {
  const gateActive = betaGateEnabled(process.env.NEXT_PUBLIC_BETA_GATE);
  const [code, setCode] = useState(initialCode?.toUpperCase() ?? "");
  const [touched, setTouched] = useState(Boolean(initialCode));
  const [status, setStatus] = useState<
    | { kind: "idle" }
    | { kind: "checking" }
    | {
        kind: "valid";
        usesRemaining: number;
        expiresAt: string | null;
      }
    | { kind: "invalid"; reason: string }
  >({ kind: "idle" });

  const validate = trpc.beta.validateInvite.useMutation();

  // Validate when the code reaches full PC-XXXX-XXXX length, debounced
  // by React's render cadence (form-level debouncing happens in onBlur).
  useEffect(() => {
    if (!gateActive) {
      onValid("");
      return;
    }
    if (!touched) return;
    const trimmed = code.trim().toUpperCase();
    if (trimmed.length !== 13) {
      setStatus({ kind: "idle" });
      onInvalid();
      return;
    }

    let cancelled = false;
    setStatus({ kind: "checking" });
    validate
      .mutateAsync({ code: trimmed })
      .then((res) => {
        if (cancelled) return;
        if (res.valid) {
          setStatus({
            kind: "valid",
            usesRemaining: res.usesRemaining,
            expiresAt: res.expiresAt,
          });
          onValid(trimmed);
        } else {
          setStatus({ kind: "invalid", reason: friendlyReason(res.reason) });
          onInvalid();
        }
      })
      .catch(() => {
        if (cancelled) return;
        setStatus({
          kind: "invalid",
          reason: "Could not reach the server. Try again.",
        });
        onInvalid();
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, touched, gateActive]);

  if (!gateActive) {
    return <>{children}</>;
  }

  return (
    <div>
      <label className="flex flex-col gap-1.5">
        <span className="font-sans text-[12px] text-graphite-soft">
          Invite code
        </span>
        <input
          type="text"
          inputMode="text"
          autoCapitalize="characters"
          spellCheck={false}
          required
          placeholder="PC-XXXX-XXXX"
          value={code}
          onChange={(e) => {
            setCode(e.target.value.toUpperCase());
            setTouched(true);
          }}
          onBlur={() => setTouched(true)}
          data-testid="invite-code-input"
          className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-mono text-[15px] tracking-widest text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
          maxLength={16}
        />
        <span className="font-sans text-[12px] text-graphite-soft">
          Paper Crane is invite-only during private beta.{" "}
          <a
            href="mailto:hello@papercrane.bio?subject=Beta%20access"
            className="text-ink underline decoration-lattice-strong underline-offset-2"
          >
            Need a code?
          </a>
        </span>
      </label>

      {status.kind === "checking" && (
        <p className="mt-2 font-sans text-[12px] text-graphite-soft">
          Checking…
        </p>
      )}
      {status.kind === "invalid" && (
        <p
          className="mt-2 rounded-xl bg-crane-glow px-3 py-2 font-sans text-[12px] text-crane-deep"
          role="alert"
        >
          {status.reason}
        </p>
      )}
      {status.kind === "valid" && (
        <p className="mt-2 rounded-xl bg-paper-fold px-3 py-2 font-sans text-[12px] text-ink">
          Welcome: invite verified.
          {status.expiresAt
            ? ` Expires ${new Date(status.expiresAt).toLocaleDateString()}.`
            : ""}
        </p>
      )}

      <div className={status.kind === "valid" ? "mt-5" : "mt-5 opacity-50 pointer-events-none"}>
        {children}
      </div>
    </div>
  );
}

function friendlyReason(reason: string): string {
  switch (reason) {
    case "unknown":
      return "We don't recognise that code. Double-check the dashes and digits.";
    case "expired":
      return "That code has expired. Ask your contact for a fresh one.";
    case "exhausted":
      return "That code has already been claimed.";
    case "malformed":
      return "Codes look like PC-XXXX-XXXX (uppercase letters and digits).";
    default:
      return "That code isn't valid.";
  }
}
