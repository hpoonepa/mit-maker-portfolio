"use client";

import { useState, type ReactNode } from "react";
import { AuditFilterBar } from "@/components/audit/AuditFilterBar";
import type { AuditFilters } from "@/components/audit/AuditTable";

/**
 * Small client wrapper: holds filter state and renders the filter bar +
 * whatever children need the active filter set. The RSC above stays
 * server-rendered except for this subtree.
 */
export function AuditFilterBarContainer({
  children,
}: {
  children: (filters: AuditFilters) => ReactNode;
}) {
  const [filters, setFilters] = useState<AuditFilters>({});
  return (
    <div className="space-y-4">
      <AuditFilterBar value={filters} onChange={setFilters} />
      {children(filters)}
    </div>
  );
}
