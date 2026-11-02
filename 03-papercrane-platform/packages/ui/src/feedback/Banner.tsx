import { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { cn } from "../utils/cn";

export type BannerVariant = "info" | "warning" | "error" | "success";

export interface BannerProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  variant?: BannerVariant;
  title?: ReactNode;
  actions?: ReactNode;
  onDismiss?: () => void;
}

const STYLES: Record<BannerVariant, { bg: string; border: string; text: string; Icon: typeof Info }> = {
  info: {
    bg: "bg-sky-50",
    border: "border-sky-200",
    text: "text-sky-900",
    Icon: Info,
  },
  warning: {
    bg: "bg-amber-50",
    border: "border-amber-200",
    text: "text-amber-950",
    Icon: AlertTriangle,
  },
  error: {
    bg: "bg-crane-glow",
    border: "border-crane/30",
    text: "text-crane-deep",
    Icon: AlertCircle,
  },
  success: {
    bg: "bg-emerald-50",
    border: "border-emerald-200",
    text: "text-emerald-900",
    Icon: CheckCircle2,
  },
};

/**
 * Inline banner for page-level messages (info / warning / error / success).
 *
 * @example
 * <Banner variant="warning" title="Low credits">Top up to keep running designs.</Banner>
 */
export const Banner = forwardRef<HTMLDivElement, BannerProps>(function Banner(
  { variant = "info", title, actions, onDismiss, className, children, ...rest },
  ref
) {
  const { bg, border, text, Icon } = STYLES[variant];
  return (
    <div
      ref={ref}
      role={variant === "error" ? "alert" : "status"}
      className={cn("flex items-start gap-3 rounded-lg border px-4 py-3 font-sans", bg, border, text, className)}
      {...rest}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 text-sm">
        {title && <p className="font-semibold">{title}</p>}
        {children && <p className={cn(title ? "mt-0.5" : "", "text-[0.85rem] opacity-90")}>{children}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      {onDismiss && (
        <button
          type="button"
          aria-label="Dismiss"
          onClick={onDismiss}
          className="ml-1 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane"
        >
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      )}
    </div>
  );
});
