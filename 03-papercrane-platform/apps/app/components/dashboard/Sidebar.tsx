"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  FolderKanban,
  FlaskConical,
  ArrowUpRight,
  LayoutGrid,
  KeyRound,
  Settings,
  Activity,
  BarChart3,
  Shapes,
  X,
} from "lucide-react";
import { useEffect } from "react";
import { cn } from "@/lib/utils";
import { getWebUrl } from "@/lib/links";
import { CraneMark } from "@/components/brand/CraneMark";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  /** If true, match exactly; otherwise match as a prefix. */
  exact?: boolean;
};

const items: NavItem[] = [
  { href: "/dashboard", label: "Overview", icon: LayoutGrid, exact: true },
  { href: "/app/projects", label: "Projects", icon: FolderKanban },
  { href: "/app/jobs", label: "Jobs", icon: Activity },
  { href: "/app/designs", label: "Designs", icon: Shapes },
  { href: "/app/tools", label: "Tools", icon: FlaskConical },
  { href: "/app/usage", label: "Usage", icon: BarChart3 },
  { href: "/app/keys", label: "API keys", icon: KeyRound },
  { href: "/app/settings", label: "Settings", icon: Settings },
];

type SidebarProps = {
  /** Whether the mobile drawer is open. Ignored at md+ (sidebar is always visible). */
  open?: boolean;
  /** Called when the user dismisses the mobile drawer (backdrop click, Escape, link tap). */
  onClose?: () => void;
};

export function Sidebar({ open = false, onClose }: SidebarProps) {
  const pathname = usePathname();

  // Close on Escape when the drawer is open. Cheap; only attaches when needed.
  useEffect(() => {
    if (!open || !onClose) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Lock body scroll while the drawer is open on mobile.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  return (
    <>
      {/* Backdrop: only on mobile, only when drawer is open. */}
      <div
        aria-hidden="true"
        onClick={onClose}
        className={cn(
          "fixed inset-0 z-40 bg-black/60 transition-opacity md:hidden",
          open
            ? "opacity-100 pointer-events-auto"
            : "opacity-0 pointer-events-none",
        )}
      />

      <aside
        aria-label="Primary"
        className={cn(
          // Mobile: fixed slide-in drawer.
          "fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col bg-paper transition-transform duration-200 ease-out",
          // Desktop: static, always visible at md+.
          "md:visible md:sticky md:top-0 md:h-screen md:z-auto md:w-56 md:max-w-none md:translate-x-0 md:flex md:shrink-0",
          open ? "visible translate-x-0" : "invisible -translate-x-full",
        )}
      >
        <div className="flex items-center justify-between gap-2 px-7 py-8">
          <Link
            href="/app"
            onClick={onClose}
            className="flex items-center gap-2.5"
            aria-label="Papercrane dashboard home"
          >
            <CraneMark className="w-8 h-8 text-crane" />
            <span className="font-sans font-medium text-[23px] lowercase tracking-[-0.055em] text-ink">
              papercrane
            </span>
          </Link>
          {/* Mobile close button: drawer dismiss for users who don't tap the backdrop. */}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close menu"
            className="md:hidden inline-flex h-11 w-11 items-center justify-center rounded-xl text-graphite hover:bg-paper-fold hover:text-ink"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <nav className="flex-1 px-7 py-10 overflow-y-auto">
          <ul className="flex flex-col gap-1">
            {items.map((item) => {
              const active = item.exact
                ? pathname === item.href
                : pathname === item.href ||
                  pathname.startsWith(item.href + "/");
              const Icon = item.icon;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onClose}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "relative flex items-center gap-3 py-3 min-h-[48px] font-sans text-[15px] transition-colors",
                      active
                        ? "text-crane font-medium"
                        : "text-graphite hover:text-ink",
                    )}
                  >
                    <Icon className="w-[18px] h-[18px]" />
                    {item.label}
                    {active && <span aria-hidden="true" className="ml-auto h-1.5 w-1.5 rounded-full bg-crane" />}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="px-7 py-7">
          <a
            href={getWebUrl()}
            onClick={onClose}
            className="flex items-center gap-2 font-sans text-[13px] text-graphite hover:text-ink transition-colors"
          >
            papercrane.bio
            <ArrowUpRight className="w-3.5 h-3.5" />
          </a>
        </div>
      </aside>
    </>
  );
}
