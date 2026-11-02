"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Loader2 } from "lucide-react";
import { trpc } from "@/lib/trpc/client";

export interface AcceptInviteClientProps {
  token: string;
  userEmail: string;
}

/**
 * Client helper for the invite acceptance page. Calls
 * `members.acceptInvite` and redirects to /home on success. Failure cases
 * (expired, wrong email, already accepted) surface inline with a clear
 * message so the user can reach out to the inviter.
 */
export function AcceptInviteClient({
  token,
  userEmail,
}: AcceptInviteClientProps) {
  const router = useRouter();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const accept = trpc.members.acceptInvite.useMutation({
    onSuccess: () => {
      setSuccess(true);
      // Give the success banner a beat to render before navigating.
      setTimeout(() => router.push("/home"), 500);
    },
    onError: (err) => setErrorMessage(err.message),
  });

  if (success) {
    return (
      <div
        role="status"
        className="flex items-center gap-2 rounded-lg border border-ink/20 bg-paper px-4 py-3 font-sans text-[14px] text-ink"
      >
        <CheckCircle2 className="h-4 w-4" />
        You're in: redirecting…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="rounded-lg border border-lattice bg-paper px-4 py-3 font-mono text-[12px] text-graphite">
        Signed in as <span className="text-ink">{userEmail}</span>
      </p>

      {errorMessage && (
        <div
          role="alert"
          className="rounded-lg border border-crane/40 bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep"
        >
          {errorMessage}
        </div>
      )}

      <button
        type="button"
        disabled={accept.isPending}
        onClick={() => accept.mutate({ token })}
        className="btn-primary w-full justify-center disabled:opacity-60"
      >
        {accept.isPending ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Accepting…
          </>
        ) : (
          "Accept invite"
        )}
      </button>

      <p className="font-sans text-[12px] text-graphite-soft">
        Wrong account? <a href="/logout" className="underline">Sign out</a> and
        come back with the email address the invite was sent to.
      </p>
    </div>
  );
}

export default AcceptInviteClient;
