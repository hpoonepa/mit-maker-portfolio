/**
 * RBAC matrix tests for the UI permissions helpers.
 *
 * The same rules are enforced in the tRPC router; these tests pin the
 * client-side contract so the two layers can be kept in sync. If a rule
 * changes, both this file AND the router tests must update.
 *
 *   viewer  → read-only
 *   member  → can create jobs/targets/projects (not covered here: this
 *             file only tests membership management)
 *   admin   → can invite, remove lower ranks, change roles (within bounds)
 *   owner   → can do everything; admin role + owner role gated to owner only
 */
import { describe, it, expect } from "vitest";
import {
  ORG_ROLES,
  assignableRolesForChange,
  assignableRolesForInvite,
  atLeast,
  canChangeRole,
  canInvite,
  canLeave,
  canRemove,
  canRevokeInvite,
  type OrgRole,
} from "@/lib/members/permissions";

const ROLES: OrgRole[] = ["viewer", "member", "admin", "owner"];

describe("ORG_ROLES", () => {
  it("lists roles from least to most privileged", () => {
    expect([...ORG_ROLES]).toEqual(["viewer", "member", "admin", "owner"]);
  });
});

describe("atLeast", () => {
  it("treats owner as the strongest role", () => {
    expect(atLeast("owner", "admin")).toBe(true);
    expect(atLeast("owner", "owner")).toBe(true);
  });
  it("says viewer is not at least member", () => {
    expect(atLeast("viewer", "member")).toBe(false);
  });
});

describe("canInvite", () => {
  it("permits owners and admins", () => {
    expect(canInvite("owner")).toBe(true);
    expect(canInvite("admin")).toBe(true);
  });
  it("rejects members and viewers", () => {
    expect(canInvite("member")).toBe(false);
    expect(canInvite("viewer")).toBe(false);
  });
});

describe("canRevokeInvite", () => {
  it("tracks canInvite: same rule", () => {
    for (const r of ROLES) {
      expect(canRevokeInvite(r)).toBe(canInvite(r));
    }
  });
});

describe("canRemove", () => {
  it("owner can remove admin, member, viewer", () => {
    expect(canRemove("owner", "admin")).toBe(true);
    expect(canRemove("owner", "member")).toBe(true);
    expect(canRemove("owner", "viewer")).toBe(true);
  });

  it("owner cannot remove another owner (both at top rank; last-owner check is separate)", () => {
    expect(canRemove("owner", "owner")).toBe(false);
  });

  it("admin can remove members and viewers, but not other admins or owners", () => {
    expect(canRemove("admin", "member")).toBe(true);
    expect(canRemove("admin", "viewer")).toBe(true);
    expect(canRemove("admin", "admin")).toBe(false);
    expect(canRemove("admin", "owner")).toBe(false);
  });

  it("members and viewers cannot remove anyone", () => {
    for (const target of ROLES) {
      expect(canRemove("member", target)).toBe(false);
      expect(canRemove("viewer", target)).toBe(false);
    }
  });

  it("refuses self-removal (use members.leave instead)", () => {
    expect(canRemove("owner", "owner", { isSelf: true })).toBe(false);
    expect(canRemove("admin", "admin", { isSelf: true })).toBe(false);
  });
});

describe("canChangeRole", () => {
  it("owner can promote/demote anyone except themselves", () => {
    expect(canChangeRole("owner", "member", "admin")).toBe(true);
    expect(canChangeRole("owner", "admin", "viewer")).toBe(true);
    expect(canChangeRole("owner", "viewer", "owner")).toBe(true);
  });

  it("owner cannot change their own role via this path", () => {
    expect(canChangeRole("owner", "owner", "admin", { isSelf: true })).toBe(false);
  });

  it("admin can flip between viewer and member", () => {
    expect(canChangeRole("admin", "viewer", "member")).toBe(true);
    expect(canChangeRole("admin", "member", "viewer")).toBe(true);
  });

  it("admin cannot grant admin or owner roles", () => {
    expect(canChangeRole("admin", "member", "admin")).toBe(false);
    expect(canChangeRole("admin", "member", "owner")).toBe(false);
  });

  it("admin cannot change another admin or an owner", () => {
    expect(canChangeRole("admin", "admin", "viewer")).toBe(false);
    expect(canChangeRole("admin", "owner", "viewer")).toBe(false);
  });

  it("members and viewers can never change roles", () => {
    for (const target of ROLES) {
      for (const next of ROLES) {
        expect(canChangeRole("member", target, next)).toBe(false);
        expect(canChangeRole("viewer", target, next)).toBe(false);
      }
    }
  });
});

describe("canLeave", () => {
  it("allows every role to leave (router enforces last-owner)", () => {
    for (const r of ROLES) {
      expect(canLeave(r)).toBe(true);
    }
  });
});

describe("assignableRolesForInvite", () => {
  it("owner may invite to any role", () => {
    expect(assignableRolesForInvite("owner")).toEqual([
      "viewer",
      "member",
      "admin",
      "owner",
    ]);
  });
  it("admin is limited to viewer and member", () => {
    expect(assignableRolesForInvite("admin")).toEqual(["viewer", "member"]);
  });
  it("member and viewer get no options", () => {
    expect(assignableRolesForInvite("member")).toEqual([]);
    expect(assignableRolesForInvite("viewer")).toEqual([]);
  });
});

describe("assignableRolesForChange", () => {
  it("mirrors assignableRolesForInvite", () => {
    for (const r of ROLES) {
      expect(assignableRolesForChange(r)).toEqual(
        assignableRolesForInvite(r),
      );
    }
  });
});
