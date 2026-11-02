import { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import { cn } from "../utils/cn";

export interface PageHeaderProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}

/**
 * Page-level header with eyebrow + title + description + right-aligned actions.
 *
 * @example
 * <PageHeader title="Runs" description="All designs" actions={<Button>New</Button>} />
 */
export const PageHeader = forwardRef<HTMLDivElement, PageHeaderProps>(function PageHeader(
  { title, description, actions, eyebrow, className, children, ...rest },
  ref
) {
  return (
    <header
      ref={ref}
      className={cn(
        "flex flex-col gap-4 border-b border-lattice pb-6 sm:flex-row sm:items-end sm:justify-between font-sans",
        className
      )}
      {...rest}
    >
      <div className="min-w-0 flex-1">
        {eyebrow && (
          <p className="mb-2 text-eyebrow font-mono uppercase text-graphite-soft">{eyebrow}</p>
        )}
        <h1 className="font-display text-display-md text-ink">{title}</h1>
        {description && <p className="mt-2 max-w-2xl text-sm text-graphite">{description}</p>}
        {children}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  );
});
