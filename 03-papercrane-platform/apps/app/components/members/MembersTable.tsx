"use client";

import { useMemo, useState } from "react";
import { MoreHorizontal, Trash2, UserCog } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import {
  assignableRolesForChange,
  canChangeRole,
  canRemove,
  type OrgRole,
} from "@/lib/members/permissions";
import { gravatarUrl } from "@/lib/members/avatar";
import {
  formatRelative,
  formatRelativeLong,
} from "@/lib/members/relativeTime";
import { RoleBadge } from "./RoleBadge";

export interface MemberRow {
  userId: string;
  email: string;
  name?: string | null;
  role: OrgRole;
  joinedAt: string | Date;
}

export interface MembersTableProps {
  /** The caller's own role in the current org. Drives the action menu. */
  actorRole: OrgRole;
  /** The caller's own user id. Used to disable self-mutating actions. */
  actorUserId: string;
  /** Initial rows from the RSC page; the table hydrates via tRPC on the client. */
  initial: MemberRow[];
}

function initials(name: string | null | undefined, email: string): string {
  const source = (name ?? email).trim();
  if (!source) return "?";
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return (parts[0]![0]! + parts[1]![0]!).toUpperCase();
}


export function MembersTable({
  actorRole,
  actorUserId,
  initial,
}: MembersTableProps) {
  const utils = trpc.useUtils();
  // The roster and invite table share this query. Partial initialData from
  // either table must not replace the other table's server-rendered rows.
  const query = trpc.members.list.useQuery();
  const rows = useMemo<MemberRow[]>(() => {
    const data = query.data as { items?: MemberRow[] } | undefined;
    return data?.items ?? initial;
  }, [query.data, initial]);

  // Owner protection: count owners so we can disable mutations on the last
  // remaining one. The server enforces this too, but surfacing it in the UI
  // stops the destructive action from ever being clickable.
  const ownerCount = useMemo(
    () => rows.filter((r) => r.role === "owner").length,
    [rows],
  );

  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const removeMutation = trpc.members.remove.useMutation({
    onSuccess: () => {
      void utils.members.list.invalidate();
    },
    onError: (err) => setErrorMessage(err.message),
  });

  const updateRoleMutation = trpc.members.updateRole.useMutation({
    onSuccess: () => {
      void utils.members.list.invalidate();
    },
    onError: (err) => setErrorMessage(err.message),
  });

  return (
    <div className="space-y-4">
      {(errorMessage || query.error) && (
        <div
          role="alert"
          className="rounded-lg border border-crane/40 bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep"
        >
          {errorMessage || "Could not refresh the team. Your last loaded members are shown."}
        </div>
      )}
      <section
        className="overflow-hidden"
        aria-label="Members"
      >
        <table className="w-full border-collapse">
          <thead className="bg-paper-fold">
            <tr className="text-left">
              <Th>Member</Th>
              <Th>Email</Th>
              <Th>Role</Th>
              <Th>Joined</Th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td
                  colSpan={5}
                  className="px-6 py-14 text-center font-sans text-[14px] text-graphite"
                >
                  No members yet.
                </td>
              </tr>
            ) : (
              rows.map((m, idx) => {
                const isSelf = m.userId === actorUserId;
                const isLastOwner = m.role === "owner" && ownerCount <= 1;
                const mayRemove =
                  canRemove(actorRole, m.role, { isSelf }) && !isLastOwner;
                const roleOptions = assignableRolesForChange(actorRole)
                  .filter(
                    (r) =>
                      r !== m.role &&
                      canChangeRole(actorRole, m.role, r, { isSelf }),
                  )
                  // Block demoting the last owner: they'd lock the org.
                  .filter(() => !isLastOwner);
                const hasActions = mayRemove || roleOptions.length > 0;
                const menuOpen = openMenuId === m.userId;
                const lastOwnerTip =
                  "This is the last owner: promote another member to owner before changing or removing this one.";

                return (
                  <tr
                    key={m.userId}
                    className={cn(
                      "hover:bg-paper/60 transition-colors",
                      idx > 0 && "border-t border-lattice",
                    )}
                  >
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-3">
                        <span
                          aria-hidden
                          className="relative inline-flex h-8 w-8 items-center justify-center overflow-hidden rounded-full border border-lattice bg-paper font-sans text-[12px] text-ink"
                        >
                          <span className="absolute inset-0 flex items-center justify-center">
                            {initials(m.name, m.email)}
                          </span>
                          <img
                            src={gravatarUrl(m.email, { size: 64 })}
                            alt=""
                            loading="lazy"
                            decoding="async"
                            className="relative z-[1] h-full w-full object-cover"
                            onError={(e) => {
                              (e.currentTarget as HTMLImageElement).style.visibility = "hidden";
                            }}
                          />
                        </span>
                        <span className="font-sans text-[14px] text-ink">
                          {m.name ?? m.email.split("@")[0]}
                          {isSelf && (
                            <span className="ml-2 font-sans text-[12px] text-graphite-soft">
                              (you)
                            </span>
                          )}
                        </span>
                      </div>
                    </td>
                    <td className="px-5 py-3 font-mono text-[13px] text-graphite">
                      {m.email}
                    </td>
                    <td className="px-5 py-3">
                      <RoleBadge role={m.role} />
                    </td>
                    <td
                      className="px-5 py-3 font-sans text-[13px] text-graphite"
                      title={formatRelativeLong(m.joinedAt)}
                    >
                      {formatRelative(m.joinedAt)}
                    </td>
                    <td className="px-5 py-3 text-right relative">
                      {hasActions ? (
                        <button
                          type="button"
                          onClick={() =>
                            setOpenMenuId(menuOpen ? null : m.userId)
                          }
                          aria-haspopup="menu"
                          aria-expanded={menuOpen}
                          aria-label={`Actions for ${m.email}`}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-transparent text-graphite hover:border-lattice hover:text-ink transition-colors"
                        >
                          <MoreHorizontal className="h-4 w-4" />
                        </button>
                      ) : isLastOwner ? (
                        <button
                          type="button"
                          disabled
                          title={lastOwnerTip}
                          aria-label={lastOwnerTip}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-transparent text-graphite-soft/60 cursor-not-allowed"
                        >
                          <MoreHorizontal className="h-4 w-4" />
                        </button>
                      ) : (
                        <span className="font-sans text-[12px] text-graphite-soft">
                          -
                        </span>
                      )}
                      {menuOpen && (
                        <div
                          role="menu"
                          className="absolute right-3 top-full z-10 mt-1 w-52 rounded-lg border border-lattice bg-paper p-1"
                        >
                          {roleOptions.map((nextRole) => (
                            <button
                              key={nextRole}
                              role="menuitem"
                              type="button"
                              disabled={updateRoleMutation.isPending}
                              onClick={() => {
                                setOpenMenuId(null);
                                updateRoleMutation.mutate({
                                  userId: m.userId,
                                  role: nextRole,
                                });
                              }}
                              className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left font-sans text-[13px] text-ink hover:bg-paper-fold"
                            >
                              <UserCog className="h-3.5 w-3.5" />
                              Make {nextRole}
                            </button>
                          ))}
                          {mayRemove && (
                            <button
                              role="menuitem"
                              type="button"
                              disabled={removeMutation.isPending}
                              onClick={() => {
                                setOpenMenuId(null);
                                const ok =
                                  typeof window === "undefined" ||
                                  window.confirm(
                                    `Remove ${m.name ?? m.email} from the org? They'll lose access immediately.`,
                                  );
                                if (!ok) return;
                                removeMutation.mutate({ userId: m.userId });
                              }}
                              className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left font-sans text-[13px] text-crane-deep hover:bg-crane-glow/60"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                              Remove from org
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
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

export default MembersTable;
