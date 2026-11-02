"use client";

import { cn } from "@/lib/utils";

export interface PageSkeletonProps {
  /** "grid" for card grids, "list" for table rows, "form" for forms. */
  variant?: "grid" | "list" | "form";
  /** Number of placeholder rows/cards. Default 6. */
  count?: number;
  className?: string;
}

/**
 * Reusable shimmer skeleton for page-level loading states.
 * Uses the same paper-fold palette as the rest of the app.
 */
export function PageSkeleton({
  variant = "grid",
  count = 6,
  className,
}: PageSkeletonProps) {
  if (variant === "list") {
    return (
      <div
        aria-busy="true"
        aria-live="polite"
        className={cn(
          "rounded-lg border border-lattice bg-paper-fold/40 overflow-hidden",
          className,
        )}
      >
        {Array.from({ length: count }).map((_, i) => (
          <div
            key={i}
            className={cn(
              "flex items-center gap-5 px-5 py-4",
              i > 0 && "border-t border-lattice",
            )}
          >
            <Shimmer className="h-4 w-32" />
            <Shimmer className="h-5 w-20 rounded-full" />
            <Shimmer className="h-4 w-16" />
            <Shimmer className="h-4 w-24" />
            <div className="flex-1" />
            <Shimmer className="h-4 w-12" />
          </div>
        ))}
      </div>
    );
  }

  if (variant === "form") {
    return (
      <div
        aria-busy="true"
        aria-live="polite"
        className={cn(
          "rounded-lg border border-lattice bg-paper-fold/40 p-7 space-y-5",
          className,
        )}
      >
        {Array.from({ length: Math.min(count, 4) }).map((_, i) => (
          <div key={i} className="space-y-2">
            <Shimmer className="h-3 w-24" />
            <Shimmer className="h-12 w-full rounded-xl" />
          </div>
        ))}
      </div>
    );
  }

  // grid
  return (
    <ul
      aria-busy="true"
      aria-live="polite"
      className={cn(
        "grid gap-4 md:grid-cols-2 xl:grid-cols-3",
        className,
      )}
    >
      {Array.from({ length: count }).map((_, i) => (
        <li
          key={i}
          className="p-6"
        >
          <Shimmer className="h-10 w-10 rounded-lg" />
          <Shimmer className="mt-5 h-6 w-3/4" />
          <Shimmer className="mt-2 h-4 w-full" />
          <Shimmer className="mt-1 h-4 w-2/3" />
          <Shimmer className="mt-5 h-3 w-24" />
        </li>
      ))}
    </ul>
  );
}

function Shimmer({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "rounded bg-paper-fold motion-safe:animate-pulse",
        className,
      )}
    />
  );
}
