import { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import { cn } from "../utils/cn";

export interface EmptyStateProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  cta?: ReactNode;
}

/**
 * Empty-state panel with icon, heading, description, and CTA slot.
 *
 * @example
 * <EmptyState icon={<Inbox />} title="No runs yet" cta={<Button>Create one</Button>} />
 */
export const EmptyState = forwardRef<HTMLDivElement, EmptyStateProps>(function EmptyState(
  { icon, title, description, cta, className, ...rest },
  ref
) {
  return (
    <div
      ref={ref}
      className={cn(
        "flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-lattice-strong bg-paper-fold/40 px-6 py-16 text-center font-sans",
        className
      )}
      {...rest}
    >
      {icon && (
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-paper-deep text-graphite">
          {icon}
        </div>
      )}
      <div className="space-y-1.5 max-w-sm">
        <h3 className="font-display text-lg text-ink tracking-tight">{title}</h3>
        {description && <p className="text-sm text-graphite">{description}</p>}
      </div>
      {cta && <div className="mt-1">{cta}</div>}
    </div>
  );
});
