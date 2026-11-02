"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type EmptyStateCta = {
  label: string;
  href?: string;
  onClick?: () => void;
};

export interface EmptyStateProps {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  primaryCta?: EmptyStateCta;
  secondaryCta?: EmptyStateCta;
  className?: string;
  /** Test hook for E2E. */
  testId?: string;
}

/**
 * Reusable empty-state panel. Used across projects, jobs, designs, etc.
 * Visual style mirrors the Paper Crane "paper fold" aesthetic.
 */
export function EmptyState({
  icon,
  title,
  description,
  primaryCta,
  secondaryCta,
  className,
  testId,
}: EmptyStateProps) {
  return (
    <div
      data-testid={testId}
      className={cn(
        "px-4 py-16 text-center",
        className,
      )}
    >
      {icon && (
        <div className="mx-auto inline-flex h-12 w-12 items-center justify-center text-crane">
          {icon}
        </div>
      )}
      <h2 className="mt-5 font-display text-[26px] text-ink tracking-[-0.01em]">
        {title}
      </h2>
      {description && (
        <p className="mt-2 mx-auto max-w-md font-sans text-[15px] text-graphite">
          {description}
        </p>
      )}
      {(primaryCta || secondaryCta) && (
        <div className="mt-6 flex items-center justify-center gap-3">
          {primaryCta && <CtaButton cta={primaryCta} variant="primary" />}
          {secondaryCta && <CtaButton cta={secondaryCta} variant="secondary" />}
        </div>
      )}
    </div>
  );
}

function CtaButton({
  cta,
  variant,
}: {
  cta: EmptyStateCta;
  variant: "primary" | "secondary";
}) {
  const className =
    variant === "primary"
      ? "btn-primary"
      : "rounded-full px-5 py-2.5 font-sans text-[14px] text-graphite hover:text-ink transition-colors";

  if (cta.href) {
    return (
      <Link href={cta.href} className={className}>
        {cta.label}
      </Link>
    );
  }
  return (
    <button type="button" onClick={cta.onClick} className={className}>
      {cta.label}
    </button>
  );
}
