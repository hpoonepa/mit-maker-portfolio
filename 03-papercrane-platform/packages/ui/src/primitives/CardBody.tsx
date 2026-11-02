import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "../utils/cn";

/**
 * Card content region with standard padding.
 *
 * @example
 * <CardBody>Content goes here</CardBody>
 */
export const CardBody = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  function CardBody({ className, ...rest }, ref) {
    return <div ref={ref} className={cn("px-5 py-4 text-sm text-ink font-sans", className)} {...rest} />;
  }
);
