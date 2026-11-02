import { forwardRef, type HTMLAttributes } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "../utils/cn";

export type SpinnerSize = "sm" | "md" | "lg";

export interface SpinnerProps extends HTMLAttributes<HTMLSpanElement> {
  size?: SpinnerSize;
  label?: string;
}

const SIZE: Record<SpinnerSize, string> = {
  sm: "h-4 w-4",
  md: "h-5 w-5",
  lg: "h-7 w-7",
};

/**
 * Indeterminate loading spinner with accessible label.
 *
 * @example
 * <Spinner size="md" label="Loading runs" />
 */
export const Spinner = forwardRef<HTMLSpanElement, SpinnerProps>(function Spinner(
  { size = "md", label = "Loading", className, ...rest },
  ref
) {
  return (
    <span
      ref={ref}
      role="status"
      aria-live="polite"
      className={cn("inline-flex items-center text-graphite", className)}
      {...rest}
    >
      <Loader2 className={cn("animate-spin", SIZE[size])} aria-hidden />
      <span className="sr-only">{label}</span>
    </span>
  );
});
