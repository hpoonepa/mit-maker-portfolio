import type { ApiKeyScope } from "@papercrane/types";

/**
 * Human-facing labels for each `ApiKeyScope` enum value.
 *
 * Used in:
 *   - <ScopeBadge />: badge text
 *   - <CreateKeyModal />: multi-select option label
 *
 * Kept tiny and pure (no i18n runtime) so it can be imported from RSC and
 * client components alike. If/when we add i18n, wrap these calls in a `t()`.
 */
const SCOPE_LABELS: Record<ApiKeyScope, string> = {
  "jobs:read": "Jobs · read",
  "jobs:write": "Jobs · write",
  "designs:read": "Designs · read",
  "targets:write": "Targets · write",
  "usage:read": "Usage · read",
  "usage:write": "Usage · write",
  "keys:manage": "Keys · manage",
  "admin:*": "Admin · all",
  "*": "All access",
};

const SCOPE_DESCRIPTIONS: Record<ApiKeyScope, string> = {
  "jobs:read": "List and inspect jobs and their designs.",
  "jobs:write": "Submit and cancel jobs.",
  "designs:read": "Download design artifacts and metrics.",
  "targets:write": "Upload new targets and edit hotspots.",
  "usage:read": "Read monthly seed consumption.",
  "usage:write": "Record seed consumption (server-to-server).",
  "keys:manage": "Create, rotate, and revoke API keys.",
  "admin:*": "Org-level admin operations.",
  "*": "Every permission, including key management. Use sparingly.",
};

export function formatScope(scope: ApiKeyScope): string {
  return SCOPE_LABELS[scope] ?? (scope as string);
}

export function formatScopeDescription(scope: ApiKeyScope): string {
  return SCOPE_DESCRIPTIONS[scope] ?? "";
}

/**
 * Canonical scope order for UI listings: read before write, narrow before
 * broad. The wildcard sits last so it never hides behind others.
 */
export const SCOPE_ORDER: readonly ApiKeyScope[] = [
  "jobs:read",
  "jobs:write",
  "designs:read",
  "targets:write",
  "usage:read",
  "usage:write",
  "keys:manage",
  "admin:*",
  "*",
];
