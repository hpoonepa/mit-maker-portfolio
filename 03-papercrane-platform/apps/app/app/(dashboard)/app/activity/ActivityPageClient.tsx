"use client";

import { useState, type ReactNode } from "react";
import { ActivityFilters } from "@/components/activity/ActivityFilters";
import type { ActivityFeedFilters } from "@/components/activity/ActivityFeed";

interface ActivityPageClientProps {
  initialFilters: ActivityFeedFilters;
  members: Array<{ id: string; name: string | null; email: string | null }>;
  projects: Array<{ id: string; name: string }>;
  children: (filters: ActivityFeedFilters) => ReactNode;
}

/**
 * Holds the filter state for the full activity page. Server page hands us the
 * org members and projects (for dropdowns) plus an initial empty-filter feed;
 * we re-render the feed via tRPC whenever the user toggles a filter.
 */
export function ActivityPageClient({
  initialFilters,
  members,
  projects,
  children,
}: ActivityPageClientProps) {
  const [filters, setFilters] = useState<ActivityFeedFilters>(initialFilters);
  return (
    <div className="space-y-5">
      <ActivityFilters
        value={filters}
        onChange={setFilters}
        members={members}
        projects={projects}
      />
      {children(filters)}
    </div>
  );
}

export default ActivityPageClient;
