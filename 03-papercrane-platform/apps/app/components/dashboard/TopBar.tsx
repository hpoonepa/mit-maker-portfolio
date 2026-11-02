"use client";

import {
  ChevronDown,
  LogOut,
  Menu,
  Search,
  Settings as SettingsIcon,
  User as UserIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useSearch } from "@/components/command/SearchProvider";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { UsageMeter } from "./UsageMeter";

type TopBarProps = {
  userEmail: string;
  userName?: string;
  orgSlug: string;
  orgName: string;
  seedsConsumed: number;
  seedsIncluded: number;
  /** Optional callback fired by the mobile hamburger button to open the nav drawer. */
  onMenuClick?: () => void;
};

export function TopBar({
  userEmail,
  userName,
  orgName,
  seedsConsumed,
  seedsIncluded,
  onMenuClick,
}: TopBarProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const { setOpen: openCommandPalette } = useSearch();

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setMenuOpen(false); };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => { window.removeEventListener("mousedown", onClick); window.removeEventListener("keydown", onKey); };
  }, []);

  const initial = (userName || userEmail).trim()[0]?.toUpperCase() ?? "?";

  return (
    <header className="sticky top-0 z-30 flex h-24 items-center justify-between gap-2 bg-paper/95 backdrop-blur-sm px-6 sm:gap-4 sm:px-8 lg:px-12">
      {/* Hamburger: only visible below md (sidebar acts as drawer there). */}
      {onMenuClick && (
        <button
          type="button"
          onClick={onMenuClick}
          aria-label="Open navigation menu"
          className="md:hidden inline-flex h-11 w-11 items-center justify-center rounded-full text-ink hover:bg-paper-fold"
        >
          <Menu className="w-5 h-5" />
        </button>
      )}

      <button
        type="button"
        onClick={() => openCommandPalette(true)}
        aria-label="Open command palette"
        className="inline-flex min-h-11 min-w-6 items-center gap-2 py-2.5 font-sans text-[13px] text-graphite transition-colors hover:text-ink"
      >
        <Search className="w-3.5 h-3.5" />
        <span className="hidden md:inline">Search…</span>
        <kbd className="hidden sm:inline font-sans text-[11px] text-graphite-soft">
          ⌘K
        </kbd>
      </button>

      <Link
        href="/app/settings"
        className="flex min-w-0 flex-1 items-center gap-2.5 text-sm text-ink md:flex-none"
        title="Workspace settings"
      >
        <span className="hidden">
          {orgName[0]?.toUpperCase() ?? "?"}
        </span>
        <span className="max-w-[130px] truncate sm:max-w-[200px]">
          {orgName}
        </span>
      </Link>

      <div className="flex items-center gap-2 sm:gap-3 md:gap-5 shrink-0">
        <Link
          href="/app/usage"
          className="hidden px-1 py-1.5 transition-colors hover:text-ink lg:flex"
        >
          <UsageMeter
            consumed={seedsConsumed}
            included={seedsIncluded}
            size="compact"
          />
        </Link>

        <NotificationBell />

        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            className="flex min-h-11 items-center gap-2 rounded-full pl-2 transition-colors hover:bg-paper-fold"
            aria-label="User menu"
            aria-expanded={menuOpen}
          >
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-paper-deep text-ink font-sans text-[12px]">
              {initial}
            </span>
            <ChevronDown className="w-3.5 h-3.5 text-graphite-soft mr-1" />
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-full mt-3 w-64 rounded-xl shadow-fold bg-surface-3 p-2">
              <div className="px-3 py-3">
                <div className="font-sans text-[13px] text-ink truncate">
                  {userName ?? userEmail}
                </div>
                {userName && (
                  <div className="font-sans text-[12px] text-graphite-soft truncate">
                    {userEmail}
                  </div>
                )}
              </div>
              <Link
                href="/app/settings"
                onClick={() => setMenuOpen(false)}
                className="flex items-center gap-3 rounded-xl px-3 py-2 font-sans text-[13px] text-ink hover:bg-paper-fold"
              >
                <UserIcon className="w-3.5 h-3.5" />
                Account
              </Link>
              <Link
                href="/app/settings"
                onClick={() => setMenuOpen(false)}
                className="flex items-center gap-3 rounded-xl px-3 py-2 font-sans text-[13px] text-ink hover:bg-paper-fold"
              >
                <SettingsIcon className="w-3.5 h-3.5" />
                Workspace settings
              </Link>
              <form action="/logout" method="post">
                <button
                  type="submit"
                  className="flex w-full items-center gap-3 rounded-xl px-3 py-2 font-sans text-[13px] text-crane-deep hover:bg-crane-glow"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  Sign out
                </button>
              </form>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
