"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";

type ProjectItem = {
  projectId: string;
  name: string;
  slug: string;
  jobCount: number;
  seedsConsumed: number;
  lastActivity: Date | string | null;
};

type ProjectsCarouselProps = {
  items: ProjectItem[];
  className?: string;
};

/**
 * Horizontally-scrollable strip of the top 5 most-active projects this
 * period. Each card shows job count, seed spend, and a relative
 * timestamp for the last activity, and links to the project detail page.
 *
 * Reads from `dashboard.getTopProjects` which ranks `Project` rows by
 * jobs in the current billing period.
 */
export function ProjectsCarousel({ items, className }: ProjectsCarouselProps) {
  if (items.length === 0) {
    return (
      <div
        className={cn(
          "px-6 py-10 text-center",
          className,
        )}
      >
        <p className="font-sans text-[13px] text-graphite">
          No active projects this period yet.
        </p>
        <Link
          href="/app/projects"
          className="mt-4 inline-flex items-center gap-2 rounded-full bg-ink px-4 py-2 font-sans text-[12px] text-paper transition-transform hover:bg-crane-deep"
        >
          Start a project →
        </Link>
      </div>
    );
  }

  return (
    <section className={cn("space-y-4", className)}>
      <div className="flex items-end justify-between">
        <div>
          <div className="font-sans text-[12px] text-graphite-soft">
            Most active projects
          </div>
          <div className="mt-2 font-sans font-medium text-[20px] tracking-[-0.01em] text-ink">
            {items.length} active projects
          </div>
        </div>
        <Link
          href="/app/projects"
          className="font-sans text-[12px] text-graphite hover:text-ink"
        >
          View all →
        </Link>
      </div>

      <div className="-mx-1 overflow-x-auto pb-2">
        <ol className="flex min-w-full gap-3 px-1">
          {items.map((p) => {
            const last = p.lastActivity
              ? typeof p.lastActivity === "string"
                ? new Date(p.lastActivity)
                : p.lastActivity
              : null;
            return (
              <li
                key={p.projectId}
                className="w-[260px] shrink-0 p-4 transition-colors"
              >
                <Link href={`/app/projects/${p.projectId}`} className="block">
                  <div className="flex items-baseline justify-between">
                    {last && (
                      <span
                        className="font-sans tabular-nums text-[12px] text-graphite-soft"
                        title={last.toISOString()}
                      >
                        {timeAgo(last)}
                      </span>
                    )}
                  </div>
                  <div className="mt-2 truncate font-sans font-medium text-[16px] tracking-[-0.01em] text-ink">
                    {p.name}
                  </div>
                  <dl className="mt-3 grid grid-cols-2 gap-2 pt-3">
                    <div>
                      <dt className="font-sans text-[12px] text-graphite-soft">
                        Jobs
                      </dt>
                      <dd className="mt-1 font-sans tabular-nums text-[16px] text-ink">
                        {p.jobCount}
                      </dd>
                    </div>
                    <div>
                      <dt className="font-sans text-[12px] text-graphite-soft">
                        Seeds
                      </dt>
                      <dd className="mt-1 font-sans tabular-nums text-[16px] text-ink">
                        {formatCount(p.seedsConsumed)}
                      </dd>
                    </div>
                  </dl>
                </Link>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}

function timeAgo(d: Date): string {
  const diffSec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (diffSec < 45) return "just now";
  if (diffSec < 3600) return `${Math.max(1, Math.floor(diffSec / 60))}m`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h`;
  return `${Math.floor(diffSec / 86400)}d`;
}

function formatCount(n: number): string {
  if (n >= 1_000_000)
    return (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1).replace(/\.0$/, "") + "k";
  return n.toString();
}
