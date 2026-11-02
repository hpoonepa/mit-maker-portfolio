import { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import { cn } from "../utils/cn";

export interface CardHeaderProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}

/**
 * Card header with title + description + optional right-aligned actions.
 *
 * @example
 * <CardHeader title="Runs" description="Last 30 days" actions={<Button>New</Button>} />
 */
export const CardHeader = forwardRef<HTMLDivElement, CardHeaderProps>(function CardHeader(
  { title, description, actions, className, children, ...rest },
  ref
) {
  return (
    <div
      ref={ref}
      className={cn(
        "flex items-start justify-between gap-4 border-b border-lattice px-5 py-4",
        className
      )}
      {...rest}
    >
      <div className="min-w-0 flex-1">
        {title && <h3 className="text-base font-semibold text-ink font-display tracking-tight">{title}</h3>}
        {description && <p className="mt-0.5 text-sm text-graphite-soft">{description}</p>}
        {children}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
});
