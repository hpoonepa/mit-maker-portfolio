"use client";

import { useState } from "react";
import { LogOut, Plus } from "lucide-react";
import { canInvite, canLeave, type OrgRole } from "@/lib/members/permissions";
import { InviteModal } from "./InviteModal";
import { LeaveOrgDialog } from "./LeaveOrgDialog";
import { MembersTable, type MemberRow } from "./MembersTable";
import {
  PendingInvitesTable,
  type PendingInvite,
} from "./PendingInvitesTable";

export interface MembersPageClientProps {
  actorRole: OrgRole;
  actorUserId: string;
  initialMembers: MemberRow[];
  initialInvites: PendingInvite[];
}

/**
 * Client-side shell wiring the members settings page. Kept separate from the
 * RSC wrapper so the whole page stays statically analysable while this
 * component owns the interactive state.
 */
export function MembersPageClient({
  actorRole,
  actorUserId,
  initialMembers,
  initialInvites,
}: MembersPageClientProps) {
  const [inviting, setInviting] = useState(false);
  const [leaving, setLeaving] = useState(false);

  const mayInvite = canInvite(actorRole);
  const mayLeave = canLeave(actorRole);

  return (
    <div className="space-y-10">
      <div className="flex items-center justify-end gap-2">
        {mayLeave && (
          <button
            type="button"
            onClick={() => setLeaving(true)}
            className="inline-flex items-center gap-1.5 rounded-full border border-lattice bg-paper px-4 py-2 font-sans text-[13px] text-graphite hover:text-ink hover:border-ink transition-colors"
          >
            <LogOut className="h-4 w-4" />
            Leave org
          </button>
        )}
        {mayInvite && (
          <button
            type="button"
            onClick={() => setInviting(true)}
            className="btn-primary"
          >
            <Plus className="h-4 w-4" />
            Invite member
          </button>
        )}
      </div>

      <PendingInvitesTable actorRole={actorRole} initial={initialInvites} />

      <MembersTable
        actorRole={actorRole}
        actorUserId={actorUserId}
        initial={initialMembers}
      />

      {inviting && (
        <InviteModal actorRole={actorRole} onClose={() => setInviting(false)} />
      )}
      {leaving && (
        <LeaveOrgDialog
          orgName="this organization"
          onClose={() => setLeaving(false)}
        />
      )}
    </div>
  );
}

export default MembersPageClient;
