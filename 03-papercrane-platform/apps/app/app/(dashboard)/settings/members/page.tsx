import { redirect } from "next/navigation";
import { createServerTrpc } from "@/lib/trpc/server";
import { getSessionUser } from "@/lib/supabase/server";
import { MembersPageClient } from "@/components/members/MembersPageClient";
import type { OrgRole } from "@/lib/members/permissions";

/**
 * Server Component: org members settings page.
 *
 * Fetches the member roster + pending invites server-side so the first paint
 * is fully rendered. The client component re-hydrates from the same tRPC
 * query for subsequent interactions (invite, role change, remove, resend).
 *
 * RBAC gating lives in the client component because this page is legal to
 * view for any member; only the action buttons are gated by role.
 */
export default async function MembersSettingsPage() {
  const user = await getSessionUser();
  if (!user) redirect("/login");

  const trpc = await createServerTrpc();

  type ListResult = Awaited<ReturnType<typeof trpc.members.list.query>>;
  let initial: ListResult;
  try {
    initial = await trpc.members.list.query();
  } catch {
    // If the user has no org yet, surface an empty state rather than 500ing.
    initial = { items: [], pendingInvites: [] } as ListResult;
  }

  const myRow = initial.items.find((m) => m.userId === user.id);
  const actorRole: OrgRole = (myRow?.role as OrgRole | undefined) ?? "viewer";

  return (
    <div className="space-y-8">
      <header className="border-b border-graphite-soft/15 pb-5">
        <p className="font-sans text-[12px] text-graphite-soft">
          Organisation
        </p>
        <h1 className=".5 font-sans text-[22px] font-medium tracking-tight text-ink">
          Members
        </h1>
        <p className="mt-1.5 max-w-xl font-sans text-[13.5px] leading-relaxed text-graphite">
          Manage who has access to this workspace. Owners and admins can
          invite teammates; everyone else can leave on their own terms.
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
