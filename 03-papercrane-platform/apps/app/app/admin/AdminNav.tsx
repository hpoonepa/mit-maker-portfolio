"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/admin/feedback", label: "feedback" },
  { href: "/admin/invites", label: "invites" },
] as const;

export function AdminNav() {
  const pathname = usePathname();
  return (
    <nav
      className="border-b border-lattice bg-paper-fold/40"
      aria-label="Admin sections"
    >
      <div className="mx-auto flex w-full max-w-6xl items-center gap-1 px-4 sm:px-6">
        <span className="mr-3 font-mono text-[11px] uppercase tracking-[0.18em] text-ink/50">
          admin
        </span>
        {TABS.map((tab) => {
          const active = pathname.startsWith(tab.href);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              className={
                "border-b-2 px-3 py-2.5 font-mono text-[12px] " +
                (active
                  ? "border-ink text-ink"
                  : "border-transparent text-ink/55 hover:text-ink")
              }
            >
              {tab.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
