import { redirect } from "next/navigation";
import { createServerTrpc } from "@/lib/trpc/server";
import { getSessionUser } from "@/lib/supabase/server";
import { MembersPageClient } from "@/components/members/MembersPageClient";
import type { OrgRole } from "@/lib/members/permissions";

/**
 * `/app/settings/team`: workspace members + invites + role assignment.
 *
 * Server-side prefetch of the members roster + pending invites so the first
 * paint is fully populated. The `<MembersPageClient>` (Wave 7) re-hydrates
 * from the same tRPC query for subsequent interactions (invite, role
 * change, remove, resend, revoke).
 *
 * RBAC gating is enforced both client-side (hidden affordances) AND in the
 * router itself: the helpers in `@/lib/members/permissions` document the
 * matrix.
 */
export default async function TeamSettingsPage() {
  const user = await getSessionUser();
  if (!user) redirect("/login");

  const trpc = await createServerTrpc();

  type ListResult = Awaited<ReturnType<typeof trpc.members.list.query>>;
  let initial: ListResult;
  try {
    initial = await trpc.members.list.query();
  } catch {
    initial = { items: [], pendingInvites: [] } as ListResult;
  }

  const myRow = initial.items.find((m) => m.userId === user.id);
  const actorRole: OrgRole = (myRow?.role as OrgRole | undefined) ?? "viewer";

  return (
    <div className="space-y-10">
      <header>
        <h1 className="font-display text-display-md text-ink">Team</h1>
        <p className="mt-2 max-w-xl font-sans text-[15px] text-graphite">
          Invite teammates and manage roles. Owners and admins can invite;
          everyone can leave. The last owner of a workspace can&apos;t be
          removed: transfer ownership first.
        </p>
      </header>

      <MembersPageClient
        actorRole={actorRole}
        actorUserId={user.id}
        initialMembers={initial.items.map((m) => ({
          userId: m.userId,
          email: m.email,
          name: m.name,
          role: m.role as OrgRole,
          joinedAt: m.joinedAt,
        }))}
        initialInvites={initial.pendingInvites.map((i) => ({
          id: i.id,
          email: i.email,
          role: i.role as OrgRole,
          invitedByName: i.invitedByName,
          invitedByEmail: i.invitedByEmail,
          expiresAt: i.expiresAt,
        }))}
      />
    </div>
  );
}
