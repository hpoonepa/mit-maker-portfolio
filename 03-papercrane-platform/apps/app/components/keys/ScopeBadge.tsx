"use client";

import type { ApiKeyScope } from "@papercrane/types";
import { cn } from "@/lib/utils";
import { formatScope } from "@/lib/keys/formatScope";

export interface ScopeBadgeProps {
  scope: ApiKeyScope;
  className?: string;
}

/**
 * Small pill used to enumerate an API key's scopes in the list view.
 *
 * Visual intent:
 *   - read-only scopes (`*:read`) use a muted lattice border
 *   - write scopes (`*:write`) use a slightly warmer tone to signal power
 *   - `keys:manage` is surfaced with a strong crane accent because misusing
 *     it bootstraps new credentials
 *   - the wildcard `*` inverts (black fill) so it can never be mistaken for a
 *     narrow scope
 *
 * Everything else falls back to the base pill. Colour only; never the sole
 * signal: the label itself still reads "Jobs · read" / "Jobs · write".
 */
function toneFor(scope: ApiKeyScope): string {
  if (scope === "*") {
    return "border-ink bg-ink text-paper";
  }
  if (scope === "keys:manage") {
    return "border-crane/60 bg-crane-glow text-crane-deep";
  }
  if (scope.endsWith(":write")) {
    return "border-lattice-strong bg-paper-fold text-ink";
  }
  return "border-lattice bg-paper text-graphite";
}

export function ScopeBadge({ scope, className }: ScopeBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 font-sans text-[12px]",
        toneFor(scope),
        className,
      )}
      title={scope}
    >
      {formatScope(scope)}
    </span>
  );
}

export default ScopeBadge;
