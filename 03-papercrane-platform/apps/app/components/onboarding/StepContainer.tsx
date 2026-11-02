/**
 * Card wrapper used by every onboarding step.
 *
 * Responsibilities
 * ----------------
 *   - consistent paper-toned card on the lattice background
 *   - title / eyebrow / body slot
 *   - footer with primary + (optional) secondary + (optional) skip buttons
 *
 * We intentionally do NOT pull from `packages/ui` so the onboarding flow
 * can ship before the design-system package is fully migrated. Any button
 * styling here is a local temporary; TODO: swap to @papercrane/ui once the
 * `Button` component is re-exported (see dashboard-migration plan).
 */
import type { ReactNode } from "react";

export interface StepAction {
  label: string;
  onClick?: () => void;
  href?: string;
  disabled?: boolean;
  type?: "button" | "submit";
}

export interface StepContainerProps {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  children: ReactNode;
  primary?: StepAction;
  secondary?: StepAction;
  skip?: StepAction;
}

// TODO(@papercrane/ui): replace with shared Button once migrated.
function InlineButton({
  action,
  variant,
}: {
  action: StepAction;
  variant: "primary" | "secondary" | "ghost";
}) {
  const base =
    "inline-flex items-center justify-center rounded-md px-5 py-2.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40";
  const styles: Record<typeof variant, string> = {
    primary: "bg-crane text-paper hover:bg-crane-deep",
    secondary: "border border-lattice-strong text-ink hover:bg-paper-fold",
    ghost: "text-graphite hover:text-ink",
  };
  const className = `${base} ${styles[variant]}`;

  if (action.href) {
    return (
      <a
        href={action.href}
        className={className}
        aria-disabled={action.disabled}
      >
        {action.label}
      </a>
    );
  }
  return (
    <button
      type={action.type ?? "button"}
      onClick={action.onClick}
      disabled={action.disabled}
      className={className}
    >
      {action.label}
    </button>
  );
}

export function StepContainer({
  eyebrow,
  title,
  subtitle,
  children,
  primary,
  secondary,
  skip,
}: StepContainerProps) {
  return (
    <div className="mx-auto w-full max-w-2xl bg-paper p-8 md:p-12">
      <header className="mb-8">
        {eyebrow && (
          <p className="mb-3 font-mono text-eyebrow uppercase text-crane">
            {eyebrow}
          </p>
        )}
        <h1 className="font-display text-3xl leading-tight tracking-tight text-ink md:text-4xl">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-3 max-w-xl text-base text-graphite">{subtitle}</p>
        )}
      </header>

      <div className="space-y-6 text-ink-soft">{children}</div>

      {(primary || secondary || skip) && (
        <footer className="mt-10 flex flex-wrap items-center justify-between gap-3 border-t border-lattice pt-6">
          <div className="flex items-center gap-3">
            {secondary && (
              <InlineButton action={secondary} variant="secondary" />
            )}
            {skip && (
              <span
                data-testid="skip-affordance"
                className="inline-flex items-baseline gap-2"
              >
                <span className="font-sans text-[0.6rem] text-graphite-soft">
                  Optional
                </span>
                <InlineButton action={skip} variant="ghost" />
              </span>
            )}
          </div>
          {primary && <InlineButton action={primary} variant="primary" />}
        </footer>
      )}
    </div>
  );
}
