import { describe, it, expect } from "vitest";
import {
  formatAuditAction,
  auditActionCategory,
  AUDIT_ACTION_LABELS,
  AUDIT_ACTIONS,
  type AuditAction,
} from "@/lib/audit/formatAction";

describe("formatAuditAction", () => {
  it("returns a human-readable label for every known action", () => {
    for (const action of AUDIT_ACTIONS) {
      const label = formatAuditAction(action);
      expect(label).toBeTruthy();
      // Labels are verb-object phrases, no raw identifiers with dots.
      expect(label).not.toMatch(/\./);
      expect(label.length).toBeGreaterThan(2);
    }
  });

  it("maps specific known actions to their expected labels", () => {
    expect(formatAuditAction("api_key.created")).toBe("Issued API key");
    expect(formatAuditAction("api_key.revoked")).toBe("Revoked API key");
    expect(formatAuditAction("api_key.rotated")).toBe("Rotated API key");
    expect(formatAuditAction("webhook.created")).toBe("Created webhook");
    expect(formatAuditAction("webhook.deleted")).toBe("Deleted webhook");
    expect(formatAuditAction("webhook.secret_rotated")).toBe(
      "Rotated webhook secret",
    );
    expect(formatAuditAction("member.invited")).toBe("Invited member");
    expect(formatAuditAction("member.removed")).toBe("Removed member");
    expect(formatAuditAction("member.role_changed")).toBe("Changed member role");
    expect(formatAuditAction("subscription.upgraded")).toBe("Upgraded plan");
    expect(formatAuditAction("subscription.downgraded")).toBe("Downgraded plan");
    expect(formatAuditAction("subscription.cancelled")).toBe("Cancelled plan");
    expect(formatAuditAction("job.cancelled")).toBe("Cancelled job");
    expect(formatAuditAction("tool_license.acknowledged")).toBe(
      "Acknowledged tool license",
    );
    expect(formatAuditAction("org.created")).toBe("Created organisation");
    expect(formatAuditAction("org.settings_updated")).toBe(
      "Updated organisation settings",
    );
  });

  it("falls back to a prettified form for unknown actions", () => {
    const label = formatAuditAction("unknown.action_thing" as AuditAction);
    // Fallback should not be the literal id and should contain a space.
    expect(label).not.toBe("unknown.action_thing");
    expect(label.toLowerCase()).toContain("action");
  });

  it("exports a stable label map covering every action id", () => {
    for (const a of AUDIT_ACTIONS) {
      expect(AUDIT_ACTION_LABELS[a]).toBeTypeOf("string");
    }
  });
});

describe("auditActionCategory", () => {
  it("groups actions by resource prefix", () => {
    expect(auditActionCategory("api_key.created")).toBe("api_key");
    expect(auditActionCategory("webhook.secret_rotated")).toBe("webhook");
    expect(auditActionCategory("member.invited")).toBe("member");
    expect(auditActionCategory("subscription.upgraded")).toBe("subscription");
    expect(auditActionCategory("job.cancelled")).toBe("job");
    expect(auditActionCategory("tool_license.acknowledged")).toBe(
      "tool_license",
    );
    expect(auditActionCategory("org.created")).toBe("org");
  });

  it("returns 'other' for ids without a dot", () => {
    expect(auditActionCategory("weird" as AuditAction)).toBe("other");
  });
});
