import type { OrgRole } from "@/lib/members/permissions";
import { cn } from "@/lib/utils";

/**
 * Small chip-style role label used in the members table and pending invites.
 * Purely presentational: colour scheme maps to the Paper Crane design
 * tokens (lattice/paper/ink) so it reads naturally in both zebra rows and
 * selection highlights.
 */
export interface RoleBadgeProps {
  role: OrgRole;
  className?: string;
}

const LABELS: Record<OrgRole, string> = {
  viewer: "Viewer",
  member: "Member",
  admin: "Admin",
  owner: "Owner",
};

const STYLES: Record<OrgRole, string> = {
  viewer: "border-lattice bg-paper-fold text-graphite",
  member: "border-lattice-strong bg-paper text-ink",
  admin: "border-ink/30 bg-paper text-ink",
  owner: "border-crane/40 bg-crane-glow text-crane-deep",
};

export function RoleBadge({ role, className }: RoleBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 font-sans text-[12px]",
        STYLES[role],
        className,
      )}
      aria-label={`Role: ${LABELS[role]}`}
    >
      {LABELS[role]}
    </span>
  );
}

export default RoleBadge;
