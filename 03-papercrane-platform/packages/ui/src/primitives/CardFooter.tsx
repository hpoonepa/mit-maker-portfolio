import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "../utils/cn";

/**
 * Card footer with top border, for actions or meta.
 *
 * @example
 * <CardFooter><Button>Save</Button></CardFooter>
 */
export const CardFooter = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  function CardFooter({ className, ...rest }, ref) {
    return (
      <div
        ref={ref}
        className={cn(
          "flex items-center justify-end gap-2 border-t border-lattice bg-paper-fold/60 px-5 py-3",
          className
        )}
        {...rest}
      />
    );
  }
);
