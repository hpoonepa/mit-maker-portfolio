import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "../utils/cn";

export type BadgeVariant = "neutral" | "crane" | "success" | "warning" | "info" | "tier";
export type BadgeSize = "sm" | "md";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  size?: BadgeSize;
  dot?: boolean;
}

const VARIANT: Record<BadgeVariant, string> = {
  neutral: "bg-paper-fold text-ink-soft border-lattice-strong",
  crane: "bg-crane-glow text-crane-deep border-crane/20",
  success: "bg-emerald-50 text-emerald-800 border-emerald-200",
  warning: "bg-amber-50 text-amber-900 border-amber-200",
  info: "bg-sky-50 text-sky-800 border-sky-200",
  tier: "bg-ink text-paper border-ink tracking-[0.2em] uppercase",
};

const SIZE: Record<BadgeSize, string> = {
  sm: "text-[10px] px-1.5 py-0.5",
  md: "text-xs px-2 py-0.5",
};

/**
 * Small status / tier pill. Use `dot` for a leading status indicator.
 *
 * @example
 * <Badge variant="crane" dot>Live</Badge>
 */
export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(function Badge(
  { variant = "neutral", size = "md", dot, className, children, ...rest },
  ref
) {
  return (
    <span
      ref={ref}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border font-sans font-medium",
        VARIANT[variant],
        SIZE[size],
        className
      )}
      {...rest}
    >
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  );
});
