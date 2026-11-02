"use client";

import Link from "next/link";
import { AlertTriangle, ArrowRight } from "lucide-react";
import type { ToolManifest, ToolTier } from "@papercrane/types";

type ToolCompatibilityWarningsProps = {
  tool: ToolManifest | null;
  userTier: ToolTier;
  /** True when estimated seeds exceed remaining quota. */
  overQuota?: boolean;
  /** Human-friendly quota surplus for the message. */
  deficit?: number;
};

const TIER_LABEL: Record<ToolTier, string> = {
  free: "Free",
  pro: "Pro",
  frontier: "Frontier",
};

/**
 * Compatibility + quota warnings between the tool and the caller's tier.
 * Renders nothing when everything is fine: keeps the form quiet by default.
 */
export function ToolCompatibilityWarnings({
  tool,
  userTier,
  overQuota,
  deficit,
}: ToolCompatibilityWarningsProps) {
  const warnings: WarningItem[] = [];

  if (tool) {
    // Tier mismatch: the tool's tier is above the caller's.
    if (tierRank(tool.tier) > tierRank(userTier)) {
      warnings.push({
        kind: "upgrade",
        message: `${tool.name} requires the ${TIER_LABEL[tool.tier]} tier. You are on ${TIER_LABEL[userTier]}.`,
        cta: { href: "/app/billing", label: "Upgrade plan" },
      });
    }
  }

  if (overQuota) {
    warnings.push({
      kind: "quota",
      message:
        typeof deficit === "number"
          ? `This job would use ${deficit.toLocaleString("en-US")} more seeds than you have remaining this period.`
          : `This job would exceed your remaining seed quota.`,
      cta: { href: "/app/billing", label: "Add seeds" },
    });
  }

  if (warnings.length === 0) return null;

  return (
    <ul
      role="list"
      aria-label="Compatibility warnings"
      className="space-y-2"
    >
      {warnings.map((w) => (
        <li
          key={w.kind}
          className="flex items-start gap-3 rounded-lg border border-crane/30 bg-crane-glow px-4 py-3"
        >
          <AlertTriangle
            className="mt-0.5 h-4 w-4 shrink-0 text-crane-deep"
            aria-hidden="true"
          />
          <div className="flex-1 font-sans text-[13px] text-crane-deep">
            {w.message}
          </div>
          {w.cta && (
            <Link
              href={w.cta.href}
              className="inline-flex items-center gap-1 font-sans text-[13px] text-crane-deep hover:underline"
            >
              {w.cta.label}
              <ArrowRight className="w-3 h-3" aria-hidden="true" />
            </Link>
          )}
        </li>
      ))}
    </ul>
  );
}

type WarningItem = {
  kind: "upgrade" | "quota";
  message: string;
  cta?: { href: string; label: string };
};

function tierRank(tier: ToolTier): number {
  return tier === "free" ? 0 : tier === "pro" ? 1 : 2;
}
