import Link from "next/link";
import { CraneMark } from "@/components/brand/CraneMark";
import type { ReactNode } from "react";

/**
 * Shared chrome for the unauthenticated auth pages (signup, forgot-password,
 * reset-password, check-email confirmation screens). The original `/login`
 * page renders its own layout for backward compatibility: over time the
 * remaining auth screens consolidate around this component.
 *
 * Keeps the on-brand paper-grain background, a small brand mark in the
 * header, and a thin footer linking to legal pages. No navbar, no command
 * palette: distractions kill conversion on auth screens.
 */
export interface AuthLayoutProps {
  /** Page heading rendered above the card. */
  title: string;
  /** Subtitle/description rendered below the heading. */
  subtitle?: ReactNode;
  /** Card body: typically a form. */
  children: ReactNode;
  /** Optional footer slot under the card (e.g. "Already have an account? …"). */
  footer?: ReactNode;
}

export function AuthLayout({ title, subtitle, children, footer }: AuthLayoutProps) {
  return (
    <div className="auth-content min-h-screen bg-paper ">
      <div className="min-h-screen flex flex-col items-center px-6 py-10">
        <div className="w-full max-w-md flex-1 flex flex-col justify-center">
          <Link
            href="/"
            className="inline-flex items-center gap-2 font-sans font-medium text-[18px] lowercase tracking-[-0.02em] text-ink"
          >
            <CraneMark className="w-8 h-8 text-crane" />
            papercrane
          </Link>

          <h1 className="mt-10 font-sans font-medium text-display-md text-ink">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-3 font-sans text-[15px] text-graphite">
              {subtitle}
            </p>
          )}

          <div className="mt-8">
            {children}
          </div>

          {footer && (
            <div className="mt-6 font-sans text-[13px] text-graphite">
              {footer}
            </div>
          )}
        </div>

        <footer className="mt-10 flex items-center gap-5 font-sans text-[12px] text-graphite-soft">
          <a href="https://papercrane.bio/terms" className="hover:text-ink">
            Terms
          </a>
          <a href="https://papercrane.bio/privacy" className="hover:text-ink">
            Privacy
          </a>
          <a href="https://papercrane.bio" className="hover:text-ink">
            papercrane.bio
          </a>
        </footer>
      </div>
    </div>
  );
}
