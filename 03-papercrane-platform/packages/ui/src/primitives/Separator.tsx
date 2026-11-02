import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "../utils/cn";

export interface SeparatorProps extends HTMLAttributes<HTMLDivElement> {
  orientation?: "horizontal" | "vertical";
}

/**
 * Hairline separator. Defaults to horizontal.
 *
 * @example
 * <Separator /> or <Separator orientation="vertical" className="h-6" />
 */
export const Separator = forwardRef<HTMLDivElement, SeparatorProps>(function Separator(
  { orientation = "horizontal", className, ...rest },
  ref
) {
  return (
    <div
      ref={ref}
      role="separator"
      aria-orientation={orientation}
      className={cn(
        "bg-lattice-strong",
        orientation === "horizontal" ? "h-px w-full" : "w-px h-full",
        className
      )}
      {...rest}
    />
  );
});
