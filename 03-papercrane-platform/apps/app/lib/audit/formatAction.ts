/**
 * Human-readable labels for audit-log action ids.
 *
 * Action ids follow a `<resource>.<verb>` convention that matches the
 * `AuditAction` enum in `packages/db/prisma/schema.prisma`. Keep the two in
 * sync: any new enum variant must get a label here so the dashboard renders
 * it as a sentence instead of a raw identifier.
 */

export const AUDIT_ACTIONS = [
  "api_key.created",
  "api_key.revoked",
  "api_key.rotated",
  "webhook.created",
  "webhook.deleted",
  "webhook.secret_rotated",
  "member.invited",
  "member.removed",
  "member.role_changed",
  "subscription.upgraded",
  "subscription.downgraded",
  "subscription.cancelled",
  "job.cancelled",
  "tool_license.acknowledged",
  "org.created",
  "org.settings_updated",
] as const;

export type AuditAction = (typeof AUDIT_ACTIONS)[number];

export const AUDIT_ACTION_LABELS: Record<AuditAction, string> = {
  "api_key.created": "Issued API key",
  "api_key.revoked": "Revoked API key",
  "api_key.rotated": "Rotated API key",
  "webhook.created": "Created webhook",
  "webhook.deleted": "Deleted webhook",
  "webhook.secret_rotated": "Rotated webhook secret",
  "member.invited": "Invited member",
  "member.removed": "Removed member",
  "member.role_changed": "Changed member role",
  "subscription.upgraded": "Upgraded plan",
  "subscription.downgraded": "Downgraded plan",
  "subscription.cancelled": "Cancelled plan",
  "job.cancelled": "Cancelled job",
  "tool_license.acknowledged": "Acknowledged tool license",
  "org.created": "Created organisation",
  "org.settings_updated": "Updated organisation settings",
};

const KNOWN = new Set<string>(AUDIT_ACTIONS);

/**
 * Return a human-readable label for an audit-action id. Unknown ids are
 * prettified by splitting on `.` / `_` so the UI never surfaces raw enum
 * values, even if an action is logged that predates this build.
 */
export function formatAuditAction(action: AuditAction | string): string {
  if (KNOWN.has(action)) {
    return AUDIT_ACTION_LABELS[action as AuditAction];
  }
  const cleaned = String(action).replace(/[._]+/g, " ").trim();
  if (!cleaned) return "Action";
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

/**
 * Category / resource prefix for filtering, grouping, and icon selection.
 * Returns `"other"` if the id isn't in `<resource>.<verb>` shape.
 */
export function auditActionCategory(action: AuditAction | string): string {
  const str = String(action);
  const dot = str.indexOf(".");
  if (dot <= 0) return "other";
  return str.slice(0, dot);
}
