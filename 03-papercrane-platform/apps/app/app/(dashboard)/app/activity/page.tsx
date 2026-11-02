import { createServerTrpc } from "@/lib/trpc/server";
import {
  ActivityFeed,
  type ActivityFeedFilters,
} from "@/components/activity/ActivityFeed";
import type { ActivityRow } from "@/components/activity/ActivityItem";
import { ActivityPageClient } from "./ActivityPageClient";

export const dynamic = "force-dynamic";
export const revalidate = 0;

/**
 * Full filterable activity timeline.
 *
 * Server-renders the first page so the initial paint is populated; the
 * client wrapper holds filter state and re-fetches via tRPC as filters
 * change. Members and projects are loaded best-effort to power the
 * dropdowns: failures degrade silently rather than blocking the page.
 */
export default async function ActivityPage() {
  const trpc = await createServerTrpc();

  let initialRows: ActivityRow[] = [];
  let initialCursor: string | null = null;
  let members: Array<{ id: string; name: string | null; email: string | null }> = [];
  let projects: Array<{ id: string; name: string }> = [];
  let fetchError: string | null = null;

  try {
    const [feed, mem, proj] = await Promise.all([
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (trpc as any).audit.list.query({ limit: 50, filters: {} }) as Promise<{
        items: ActivityRow[];
        nextCursor: string | null;
      }>,
      trpc.members.list
        .query()
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .catch(() => ({ items: [] }) as any),
      trpc.projects.list
        .query({ limit: 100 })
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .catch(() => ({ items: [] }) as any),
    ]);
    initialRows = feed.items ?? [];
    initialCursor = feed.nextCursor ?? null;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    members = ((mem as any).items ?? []).map((m: any) => ({
      id: m.userId ?? m.id,
      name: m.name ?? null,
      email: m.email ?? null,
    }));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    projects = ((proj as any).items ?? []).map((p: any) => ({
      id: p.id,
      name: p.name,
    }));
  } catch (e) {
    fetchError = e instanceof Error ? e.message : "Failed to load activity.";
  }

  const initialFilters: ActivityFeedFilters = {};

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-display-md text-ink">Activity</h1>
        <p className="mt-2 max-w-2xl font-sans text-[15px] text-graphite">
          Everything that happens in your org: projects, jobs, designs,
          members, billing, and webhooks. Click an entry to jump to it.
        </p>
      </header>

      {fetchError && (
        <div
          role="alert"
          className="rounded-lg border border-crane/40 bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep"
        >
          {fetchError}
        </div>
      )}

      <ActivityPageClient
        members={members}
        projects={projects}
        initialFilters={initialFilters}
      >
        {(filters) => (
          <ActivityFeed
            initialRows={initialRows}
            initialNextCursor={initialCursor}
            filters={filters}
            limit={50}
            emptyCta={{ href: "/app/projects", label: "Create a project" }}
          />
        )}
      </ActivityPageClient>
    </div>
  );
}
