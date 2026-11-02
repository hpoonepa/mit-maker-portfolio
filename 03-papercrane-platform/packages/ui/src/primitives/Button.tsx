import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "../utils/cn";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
}

const VARIANT: Record<ButtonVariant, string> = {
  // Crane-red primary with hairline inner highlight for tactile depth (no drop-shadow-lg)
  primary:
    "bg-crane text-paper border border-crane-deep/60 hover:bg-crane-deep active:bg-crane-deep " +
    "shadow-[inset_0_1px_0_rgba(255,255,255,0.12),0_1px_0_rgba(20,17,13,0.12)] active:shadow-[inset_0_1px_0_rgba(20,17,13,0.18)]",
  // Secondary: paper-fold with hairline that darkens on hover (Stripe-tier definition)
  secondary:
    "bg-paper-fold text-ink border border-lattice-strong hover:bg-paper-deep hover:border-ink/30 active:bg-paper-deep",
  // Ghost: text-only, hover brings a subtle paper-fold wash + border ghost
  ghost:
    "bg-transparent text-ink border border-transparent hover:bg-paper-fold hover:border-lattice",
  // Danger: deeper crane, identical hairline treatment to primary for visual consistency
  danger:
    "bg-crane-deep text-paper border border-ink/40 hover:bg-crane active:bg-crane-deep " +
    "shadow-[inset_0_1px_0_rgba(255,255,255,0.10),0_1px_0_rgba(20,17,13,0.16)]",
};

const SIZE: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
  lg: "h-12 px-6 text-base gap-2.5",
};

const BASE =
  "inline-flex items-center justify-center rounded-md font-sans font-medium tracking-tight " +
  "transition-[background-color,border-color,box-shadow,color] duration-150 ease-out select-none whitespace-nowrap " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane focus-visible:ring-offset-2 focus-visible:ring-offset-paper " +
  "disabled:opacity-50 disabled:pointer-events-none disabled:shadow-none";

/**
 * Primary interactive button. Supports variants, sizes, and loading state.
 *
 * @example
 * <Button variant="primary" size="md" onClick={save}>Save</Button>
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    size = "md",
    loading = false,
    leftIcon,
    rightIcon,
    className,
    children,
    disabled,
    type = "button",
    ...rest
  },
  ref
) {
  const isDisabled = disabled || loading;
  return (
    <button
      ref={ref}
      type={type}
      aria-busy={loading || undefined}
      disabled={isDisabled}
      className={cn(BASE, VARIANT[variant], SIZE[size], className)}
      {...rest}
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
      ) : leftIcon ? (
        <span aria-hidden="true" className="inline-flex">
          {leftIcon}
        </span>
      ) : null}
      {children}
      {!loading && rightIcon ? (
        <span aria-hidden="true" className="inline-flex">
          {rightIcon}
        </span>
      ) : null}
    </button>
  );
});
