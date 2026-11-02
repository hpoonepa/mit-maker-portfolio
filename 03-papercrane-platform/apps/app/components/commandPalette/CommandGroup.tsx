"use client";

import type { ReactNode } from "react";

interface CommandGroupProps {
  heading: string;
  children: ReactNode;
}

/**
 * Section header + body wrapper. One heading per result group
 * (Navigation, Actions, Projects, Jobs, Targets, Tools, Docs, Recent).
 */
export function CommandGroup({ heading, children }: CommandGroupProps) {
  return (
    <section className="mb-1 last:mb-0">
      <h3 className="px-3 pb-1 pt-2 font-sans text-eyebrow uppercase text-graphite-soft">
        {heading}
      </h3>
      <div className="flex flex-col" role="group" aria-label={heading}>
        {children}
      </div>
    </section>
  );
}
