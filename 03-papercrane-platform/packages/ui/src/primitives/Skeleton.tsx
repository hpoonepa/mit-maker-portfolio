import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "../utils/cn";

export interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  /** Render as a circle (e.g. avatar placeholder). */
  circle?: boolean;
}

/**
 * Loading placeholder. Pair with explicit height / width classes.
 *
 * @example
 * <Skeleton className="h-4 w-40" />
 */
export const Skeleton = forwardRef<HTMLDivElement, SkeletonProps>(
  function Skeleton({ className, circle, ...rest }, ref) {
    return (
      <div
        ref={ref}
        role="status"
        aria-live="polite"
        aria-busy="true"
        className={cn(
          "relative overflow-hidden bg-paper-deep",
          circle ? "rounded-full" : "rounded-md",
          "motion-safe:animate-pulse",
          className,
        )}
        style={{
          ...(rest.style ?? {}),
        }}
        {...rest}
      >
        <span className="sr-only">Loading…</span>
      </div>
    );
  },
);
