"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import {
  formatGraceRemaining,
  graceRemainingMs,
  keyStatus,
  type KeyRecord,
  type KeyStatus,
} from "@/lib/keys/rotation";

export interface KeyStatusPillProps {
  k: KeyRecord;
  className?: string;
}

/**
 * Single pill that collapses status + grace-countdown into one affordance.
 *
 * For rotating keys we tick a 30-second interval so the countdown refreshes
 * without forcing a parent re-render. No setInterval runs for non-rotating
 * keys (common case), so the list stays cheap.
 */
const LABELS: Record<KeyStatus, string> = {
  active: "Active",
  rotating: "Rotating",
  revoked: "Revoked",
  expired: "Expired",
};

const TONES: Record<KeyStatus, string> = {
  active: "border-lattice bg-paper text-ink",
  rotating: "border-crane/60 bg-crane-glow text-crane-deep",
  revoked: "border-lattice bg-paper-fold text-graphite",
  expired: "border-lattice bg-paper-fold text-graphite",
};

const DOT_TONES: Record<KeyStatus, string> = {
  active: "bg-ink",
  rotating: "bg-crane animate-pulse",
  revoked: "bg-graphite-soft",
  expired: "bg-graphite-soft",
};

export function KeyStatusPill({ k, className }: KeyStatusPillProps) {
  const [, force] = useState(0);
  const status = keyStatus(k);

  // Countdown ticker: only arms for rotating keys.
  useEffect(() => {
    if (status !== "rotating") return;
    const id = setInterval(() => force((n) => n + 1), 30_000);
    return () => clearInterval(id);
  }, [status]);

  const remainingLabel =
    status === "rotating"
      ? formatGraceRemaining(graceRemainingMs(k))
      : null;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-sans text-[12px]",
        TONES[status],
        className,
      )}
      title={
        status === "rotating" && remainingLabel
          ? `Old key valid for ${remainingLabel} (24h grace window)`
          : LABELS[status]
      }
    >
      <span className={cn("inline-block h-1.5 w-1.5 rounded-full", DOT_TONES[status])} />
      {LABELS[status]}
      {remainingLabel && (
        <span className="font-sans normal-case tracking-normal text-[11px] text-crane-deep/80">
          · {remainingLabel} left
        </span>
      )}
    </span>
  );
}

export default KeyStatusPill;
