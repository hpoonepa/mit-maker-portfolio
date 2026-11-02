/**
 * Role-based access-control (RBAC) helpers for organization member management.
 *
 * These helpers encode the invariants documented in CLAUDE.md:
 *
 *   viewer  → read-only, cannot invite or change anything
 *   member  → can submit jobs, create targets/projects
 *   admin   → above + can invite/remove members, rotate webhooks/keys
 *   owner   → above + billing, delete org, transfer ownership.
 *             Last owner cannot be removed (enforced in the router).
 *
 * The functions below are pure: no DB access, no side effects: so they
 * work in both RSC and client components and are trivially unit-testable.
 *
 * The SAME matrix is enforced in the tRPC router; the UI helpers are a
 * convenience for hiding buttons/menu-items that the server would reject
 * anyway. Never trust them as the sole gate.
 */

export type OrgRole = "viewer" | "member" | "admin" | "owner";

export const ORG_ROLES: readonly OrgRole[] = [
  "viewer",
  "member",
  "admin",
  "owner",
] as const;

/** Rank used for "X is at least as privileged as Y" comparisons. */
const RANK: Record<OrgRole, number> = {
  viewer: 0,
  member: 1,
  admin: 2,
  owner: 3,
};

/** True if `actor` ranks strictly higher than `target`. */
function outranks(actor: OrgRole, target: OrgRole): boolean {
  return RANK[actor] > RANK[target];
}

/** True if `a` has at least the rank of `b`. */
export function atLeast(a: OrgRole, b: OrgRole): boolean {
  return RANK[a] >= RANK[b];
}

/**
 * Can the actor invite new members to the org?
 * Only owners and admins may invite.
 */
export function canInvite(actor: OrgRole): boolean {
  return actor === "owner" || actor === "admin";
}

/**
 * Can the actor revoke a pending invite?
 * Same rule as inviting: you created it, you can unsend it.
 */
export function canRevokeInvite(actor: OrgRole): boolean {
  return canInvite(actor);
}

/**
 * Can the actor remove an existing member?
 *
 * Rules:
 *  - actor must be owner or admin
 *  - actor must strictly outrank the target (admins cannot remove other admins
 *    or owners; owners can remove anyone subject to the "last owner" rule
 *    enforced in the router)
 *  - actor may never remove themselves via this code path: use
 *    `members.leave` for self-removal so the "last owner" check still applies
 *    consistently
 */
export function canRemove(
  actor: OrgRole,
  target: OrgRole,
  opts: { isSelf?: boolean } = {},
): boolean {
  if (opts.isSelf) return false;
  if (actor !== "owner" && actor !== "admin") return false;
  return outranks(actor, target);
}

/**
 * Can the actor change another member's role to `nextRole`?
 *
 * Rules:
 *  - actor must be owner or admin
 *  - actor must strictly outrank the *current* target role
 *  - actor must also have the rank required to grant `nextRole`
 *    (admin can promote viewer→member, but cannot promote to admin or owner;
 *    only an owner can create/grant the owner role)
 *  - an admin cannot grant the `owner` role at all
 *  - nobody can change their own role through this path (transfer ownership
 *    is its own flow)
 */
export function canChangeRole(
  actor: OrgRole,
  target: OrgRole,
  nextRole: OrgRole,
  opts: { isSelf?: boolean } = {},
): boolean {
  if (opts.isSelf) return false;
  if (actor !== "owner" && actor !== "admin") return false;
  if (!outranks(actor, target)) return false;

  // The granted role must be one the actor is itself privileged to hand out.
  // "owner" can only be granted by an owner.
  if (nextRole === "owner" && actor !== "owner") return false;

  // Admins cannot promote someone to admin (that would let them escalate
  // laterally via a sympathetic target). Only owners can mint new admins.
  if (nextRole === "admin" && actor !== "owner") return false;

  return true;
}

/**
 * Can the actor leave the org?
 * Anyone may leave; the router additionally refuses the call when the caller
 * is the last `owner` to preserve the "orgs always have an owner" invariant.
 */
export function canLeave(_actor: OrgRole): boolean {
  return true;
}

/**
 * Which roles is `actor` allowed to assign on an invite form?
 * Used to populate the role <select> in `InviteModal`.
 */
export function assignableRolesForInvite(actor: OrgRole): OrgRole[] {
  if (actor === "owner") return ["viewer", "member", "admin", "owner"];
  if (actor === "admin") return ["viewer", "member"];
  return [];
}

/**
 * Which roles is `actor` allowed to change an existing member *to*?
 * Admins can only juggle between viewer and member; owners can grant any role.
 */
export function assignableRolesForChange(actor: OrgRole): OrgRole[] {
  if (actor === "owner") return ["viewer", "member", "admin", "owner"];
  if (actor === "admin") return ["viewer", "member"];
  return [];
}
