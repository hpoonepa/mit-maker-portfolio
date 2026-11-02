import { forwardRef, type HTMLAttributes } from "react";
import { cn } from "../utils/cn";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** When true, adds a subtle hover lift. */
  interactive?: boolean;
  /** Remove default padding; use Card.Header/Body/Footer for sectioned layout. */
  bare?: boolean;
}

/**
 * Surface container with paper-toned background and lattice border.
 *
 * @example
 * <Card><CardHeader title="Runs" /><CardBody>…</CardBody></Card>
 */
export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { interactive, bare, className, ...rest },
  ref
) {
  return (
    <div
      ref={ref}
      className={cn(
        // Editorial surface: hairline border, single-pixel grounded shadow (no drop-shadow-lg)
        "rounded-lg bg-paper border border-lattice-strong shadow-[0_1px_0_rgba(20,17,13,0.04)] font-sans",
        // Interactive: border darkens + faint paper-deep ground (no translate, no scale)
        interactive &&
          "cursor-pointer transition-[border-color,box-shadow,background-color] duration-200 ease-out " +
            "hover:border-ink/30 hover:shadow-[0_2px_0_rgba(20,17,13,0.06)] hover:bg-paper-fold/40 " +
            "focus-within:border-crane focus-within:shadow-[0_0_0_3px_rgba(193,39,45,0.12)]",
        !bare && "overflow-hidden",
        className
      )}
      {...rest}
    />
  );
});
