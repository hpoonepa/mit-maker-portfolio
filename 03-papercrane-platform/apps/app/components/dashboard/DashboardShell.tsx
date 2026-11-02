"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { JobCompletionAlerts } from "@/components/jobs/JobCompletionAlerts";
import { trpc } from "@/lib/trpc/client";

type DashboardShellProps = {
  userEmail: string;
  userName?: string;
  orgSlug: string;
  orgName: string;
  seedsConsumed: number;
  seedsIncluded: number;
  children: ReactNode;
};

/**
 * Client shell that wraps the dashboard layout. Owns the mobile-sidebar
 * drawer state so the topbar's hamburger and the sidebar's backdrop can
 * coordinate without bubbling state through the server `layout.tsx`.
 *
 * Sidebar + TopBar already handle the responsive show/hide; this just
 * keeps the open/close state and closes the drawer on route change so
 * users don't land on a new page with the menu still covering it.
 */
export function DashboardShell({
  userEmail,
  userName,
  orgSlug,
  orgName,
  seedsConsumed,
  seedsIncluded,
  children,
}: DashboardShellProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const pathname = usePathname();
  const usage = trpc.usage.getCurrentPeriodUsage.useQuery(undefined, {
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });

  // Auto-close the drawer whenever the route changes: users tapping a nav
  // link expect to land on the new page, not still see the menu over it.
  useEffect(() => {
    setDrawerOpen(false);
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [pathname]);

  return (
    <JobCompletionAlerts key={`${orgSlug}:${userEmail}`} scope={`${orgSlug}:${userEmail}`}>
    <div className="workspace-shell flex min-h-screen bg-paper">
      <Sidebar open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar
          userEmail={userEmail}
          userName={userName}
          orgSlug={orgSlug}
          orgName={orgName}
          seedsConsumed={usage.data?.seedsConsumed ?? seedsConsumed}
          seedsIncluded={usage.data?.seedsIncluded ?? seedsIncluded}
          onMenuClick={() => setDrawerOpen(true)}
        />
        <main id="main-content" tabIndex={-1} className="workspace-content flex-1 px-6 pb-16 pt-6 sm:px-8 lg:px-12 lg:pt-10">
          <div className="mx-auto w-full max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
    </JobCompletionAlerts>
  );
}
