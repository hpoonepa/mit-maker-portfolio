"use client";

import Link from "next/link";
import { Copy } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * "Duplicate job" button for the job detail page.
 *
 * Pure navigation: links to `/app/jobs/[id]/duplicate`, which is a
 * server component that hydrates the source job's params and redirects
 * to the new-job form pre-filled. Kept as a `<Link>` (no client state)
 * so it works without JS and prefetches naturally.
 *
 * Owned by Wave-A Agent 8. The detail page (Agent A4) imports this
 * component into its action bar; this file does NOT touch the detail
 * page itself.
 */

interface DuplicateJobButtonProps {
  jobId: string;
  className?: string;
  /** Optional label override; defaults to "Duplicate". */
  label?: string;
}

export function DuplicateJobButton({
  jobId,
  className,
  label = "Duplicate",
}: DuplicateJobButtonProps) {
  return (
    <Link
      href={`/app/jobs/${encodeURIComponent(jobId)}/duplicate`}
      prefetch={false}
      aria-label={`Duplicate job ${jobId}`}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg border border-lattice bg-paper px-3 py-1.5",
        "font-sans text-[12px] text-graphite",
        "hover:text-ink hover:border-ink transition-colors",
        className,
      )}
    >
      <Copy className="w-3 h-3" aria-hidden="true" />
      {label}
    </Link>
  );
}

export default DuplicateJobButton;
