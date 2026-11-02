"use client";

import { useEffect, useState } from "react";
import { Mail, X } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import {
  assignableRolesForInvite,
  type OrgRole,
} from "@/lib/members/permissions";

export interface InviteModalProps {
  /** Caller's role. Drives which roles appear in the dropdown. */
  actorRole: OrgRole;
  /** Called when the modal should close (cancel button, Esc, or success). */
  onClose: () => void;
}

/**
 * Modal dialog for inviting a teammate. Lives inside the members settings
 * page; render it conditionally rather than keeping it mounted so focus
 * management is simple (first field focuses on open).
 */
export function InviteModal({ actorRole, onClose }: InviteModalProps) {
  const utils = trpc.useUtils();

  const options = assignableRolesForInvite(actorRole);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<OrgRole>(options[0] ?? "member");
  const [topError, setTopError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);

  const invite = trpc.members.invite.useMutation({
    onSuccess: (result) => {
      void utils.members.list.invalidate();
      // In dev (and any environment without a real SMTP transport) the email
      // dispatch is best-effort. Surface the accept URL to the browser
      // console so the inviter can copy it manually until Resend/Postmark
      // are wired up.
      const token = (result?.invite as { token?: string } | null)?.token;
      const email = (result?.invite as { email?: string } | null)?.email;
      if (token && typeof window !== "undefined") {
        const acceptUrl = `${window.location.origin}/invite/${encodeURIComponent(token)}`;

        console.info(
          `[papercrane] invite created → ${email ?? "?"}\n  ${acceptUrl}`,
        );
      }
      onClose();
    },
    onError: (err) => {
      setTopError(err.message ?? "Could not send invite");
    },
  });

  // Esc closes the modal. Using an effect hook keeps the listener scoped to
  // the lifetime of the mounted dialog.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setTopError(null);
    const trimmed = email.trim();
    if (!trimmed) {
      setFieldError("Enter an email address");
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) {
      setFieldError("That email doesn't look right");
      return;
    }
    setFieldError(null);
    invite.mutate({ email: trimmed, role });
  };

  if (options.length === 0) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="invite-modal-title"
    >
      <form
        onSubmit={onSubmit}
        noValidate
        className="relative w-full max-w-md rounded-lg border border-lattice bg-paper p-6"
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute right-4 top-4 inline-flex h-8 w-8 items-center justify-center rounded-full text-graphite hover:bg-paper-fold"
        >
          <X className="h-4 w-4" />
        </button>

        <h3
          id="invite-modal-title"
          className="font-display text-[22px] text-ink"
        >
          Invite a teammate
        </h3>
        <p className="mt-1 font-sans text-[13px] text-graphite">
          They'll receive an email with a magic-link invite. Invites expire in
          7 days.
        </p>

        {topError && (
          <div
            role="alert"
            className="mt-4 rounded-lg border border-crane/40 bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep"
          >
            {topError}
          </div>
        )}

        <label className="mt-5 flex flex-col gap-1.5">
          <span className="font-sans text-[12px] text-graphite-soft">
            Email
          </span>
          <input
            type="email"
            required
            autoFocus
            maxLength={320}
            placeholder="teammate@lab.edu"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={fieldError ? true : undefined}
            aria-describedby={fieldError ? "invite-email-err" : undefined}
            className={cn(
              "rounded-xl border bg-paper px-4 py-3 font-sans text-[15px] text-ink focus:outline-none",
              fieldError
                ? "border-crane focus:border-crane-deep"
                : "border-lattice-strong focus:border-ink",
            )}
          />
          {fieldError && (
            <span
              id="invite-email-err"
              className="font-sans text-[12px] text-crane-deep"
            >
              {fieldError}
            </span>
          )}
        </label>

        <label className="mt-4 flex flex-col gap-1.5">
          <span className="font-sans text-[12px] text-graphite-soft">
            Role
          </span>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as OrgRole)}
            className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[15px] text-ink focus:border-ink focus:outline-none"
          >
            {options.map((r) => (
              <option key={r} value={r}>
                {r[0]!.toUpperCase() + r.slice(1)}
              </option>
            ))}
          </select>
        </label>

        <div className="mt-6 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-full px-5 py-2.5 font-sans text-[14px] text-graphite hover:text-ink transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={invite.isPending}
            className="btn-primary disabled:opacity-60"
          >
            <Mail className="h-4 w-4" />
            {invite.isPending ? "Sending…" : "Send invite"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default InviteModal;
