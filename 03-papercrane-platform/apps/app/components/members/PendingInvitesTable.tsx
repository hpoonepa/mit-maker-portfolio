"use client";

import { useMemo, useState } from "react";
import { Trash2, Send } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import { canRevokeInvite, type OrgRole } from "@/lib/members/permissions";
import { RoleBadge } from "./RoleBadge";

export interface PendingInvite {
  id: string;
  email: string;
  role: OrgRole;
  invitedByName?: string | null;
  invitedByEmail?: string | null;
  expiresAt: string | Date;
}

export interface PendingInvitesTableProps {
  actorRole: OrgRole;
  initial: PendingInvite[];
}

function formatRelative(d: string | Date): string {
  const date = typeof d === "string" ? new Date(d) : d;
  if (Number.isNaN(date.getTime())) return "N/A";
  const deltaMs = date.getTime() - Date.now();
  const days = Math.round(deltaMs / (24 * 60 * 60 * 1000));
  if (days < 0) return "expired";
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}

export function PendingInvitesTable({
  actorRole,
  initial,
}: PendingInvitesTableProps) {
  const utils = trpc.useUtils();
  const query = trpc.members.list.useQuery();
  const rows = useMemo<PendingInvite[]>(() => {
    const data = query.data as { pendingInvites?: PendingInvite[] } | undefined;
    return data?.pendingInvites ?? initial;
  }, [query.data, initial]);

  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const revoke = trpc.members.removeInvite.useMutation({
    onSuccess: () => {
      void utils.members.list.invalidate();
    },
    onError: (err) => setErrorMessage(err.message),
  });

  // Dedicated resend: bumps `expiresAt` and rotates the token on the server
  // so the old link can no longer be used. We surface the fresh accept URL to
  // the dev console so local testing doesn't require a real SMTP connection.
  const resend = trpc.members.resendInvite.useMutation({
    onSuccess: (inv) => {
      void utils.members.list.invalidate();
      const token = (inv as { token?: string } | null)?.token;
      const email = (inv as { email?: string } | null)?.email;
      if (token && typeof window !== "undefined") {
        const acceptUrl = `${window.location.origin}/invite/${encodeURIComponent(token)}`;

        console.info(
          `[papercrane] invite resent → ${email ?? "?"}\n  ${acceptUrl}`,
        );
      }
    },
    onError: (err) => setErrorMessage(err.message),
  });

  const mayMutate = canRevokeInvite(actorRole);

  if (rows.length === 0) {
    return null;
  }

  return (
    <div className="space-y-4">
      {errorMessage && (
        <div
          role="alert"
          className="rounded-lg border border-crane/40 bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep"
        >
          {errorMessage}
        </div>
      )}
      <section
        className="overflow-hidden"
        aria-label="Pending invites"
      >
        <div className="px-6 py-4 flex items-center justify-between">
          <h2 className="font-display text-[18px] text-ink">
            Pending invites
          </h2>
          <span className="font-sans text-[12px] text-graphite-soft">
            {rows.length} pending
          </span>
        </div>
        <table className="w-full border-collapse">
          <thead className="bg-paper-fold">
            <tr className="text-left">
              <Th>Email</Th>
              <Th>Role</Th>
              <Th>Invited by</Th>
              <Th>Expires</Th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((inv, idx) => (
              <tr
                key={inv.id}
                className={cn(
                  "hover:bg-paper/60 transition-colors",
                  idx > 0 && "border-t border-lattice",
                )}
              >
                <td className="px-5 py-3 font-mono text-[13px] text-ink">
                  {inv.email}
                </td>
                <td className="px-5 py-3">
                  <RoleBadge role={inv.role} />
                </td>
                <td className="px-5 py-3 font-sans text-[13px] text-graphite">
                  {inv.invitedByName ?? inv.invitedByEmail ?? "N/A"}
                </td>
                <td className="px-5 py-3 font-sans text-[13px] text-graphite">
                  {formatRelative(inv.expiresAt)}
                </td>
                <td className="px-5 py-3 text-right">
                  {mayMutate ? (
                    <div className="inline-flex gap-1">
                      <button
                        type="button"
                        disabled={resend.isPending}
                        onClick={() => resend.mutate({ inviteId: inv.id })}
                        className="inline-flex items-center gap-1 rounded-full border border-lattice bg-paper px-3 py-1.5 font-sans text-[12px] text-ink hover:border-ink transition-colors disabled:opacity-50"
                        aria-label={`Resend invite to ${inv.email}`}
                      >
                        <Send className="h-3.5 w-3.5" />
                        Resend
                      </button>
                      <button
                        type="button"
                        disabled={revoke.isPending}
                        onClick={() => {
                          const ok =
                            typeof window === "undefined" ||
                            window.confirm(
                              `Revoke the invite to ${inv.email}? Their accept link will stop working.`,
                            );
                          if (!ok) return;
                          revoke.mutate({ inviteId: inv.id });
                        }}
                        className="inline-flex items-center gap-1 rounded-full border border-transparent px-3 py-1.5 font-sans text-[12px] text-crane-deep hover:border-crane/40 hover:bg-crane-glow/60 transition-colors disabled:opacity-50"
                        aria-label={`Revoke invite to ${inv.email}`}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Revoke
                      </button>
                    </div>
                  ) : (
                    <span className="font-sans text-[12px] text-graphite-soft">
                      -
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-5 py-3 font-sans text-[12px] text-graphite-soft">
      {children}
    </th>
  );
}

export default PendingInvitesTable;
