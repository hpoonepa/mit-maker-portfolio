"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";

export interface SectionCardProps {
  href: string;
  /**
   * Pre-rendered icon element (e.g. `<User className="h-4 w-4" />`).
   * We take a ReactNode rather than a component reference so this client
   * boundary doesn't try to serialize a function from the server page -
   * Next.js refuses that with "Functions cannot be passed directly to
   * Client Components".
   */
  icon: ReactNode;
  title: string;
  description: string;
  /** Optional small caption rendered top-right (e.g. "3 keys", "Pro"). */
  meta?: string;
}

/**
 * Settings landing-page nav card. Renders a link tile with an icon,
 * a title, a short description, and an arrow affordance on hover.
 *
 * Uses the same paper-fold + lattice palette as the rest of the dashboard
 * so the section cards feel like part of the broader navigation rather
 * than a separate widget.
 */
export function SectionCard({
  href,
  icon,
  title,
  description,
  meta,
}: SectionCardProps) {
  return (
    <Link
      href={href}
      className="group relative flex flex-col gap-4 py-7 pr-10 transition-colors"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="inline-flex h-6 w-6 items-center text-crane transition-colors">
          {icon}
        </div>
        {meta ? (
          <span className="font-sans text-[12px] text-graphite-soft">
            {meta}
          </span>
        ) : null}
      </div>

      <div>
        <h3 className="font-display text-[23px] tracking-tight text-ink group-hover:text-crane">{title}</h3>
        <p className="mt-1 font-sans text-[13px] leading-relaxed text-graphite">
          {description}
        </p>
      </div>

      <ChevronRight
        aria-hidden="true"
        className="absolute top-8 right-4 h-4 w-4 text-graphite-soft transition-transform group-hover:translate-x-0.5 group-hover:text-ink"
      />
    </Link>
  );
}

export default SectionCard;
