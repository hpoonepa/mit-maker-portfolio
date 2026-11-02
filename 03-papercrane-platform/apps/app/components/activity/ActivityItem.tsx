"use client";

import Link from "next/link";
import {
  Activity,
  CreditCard,
  Folder,
  Key,
  Play,
  Send,
  Settings,
  Target,
  UserPlus,
  Webhook,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

export interface ActivityRow {
  id: string;
  orgId: string;
  userId: string | null;
  action: string;
  resourceType: string | null;
  resourceId: string | null;
  metadata: Record<string, unknown> | null;
  createdAt: string | Date;
  actorEmail?: string | null;
  actorName?: string | null;
  /** Optional rollup count for grouped sequential entries (e.g. "5 designs"). */
  groupCount?: number;
}

/** Map an action category to a feed icon. */
const CATEGORY_ICON: Record<string, LucideIcon> = {
  project: Folder,
  target: Target,
  job: Play,
  design: Send,
  api_key: Key,
  key: Key,
  webhook: Webhook,
  member: UserPlus,
  subscription: CreditCard,
  billing: CreditCard,
  org: Settings,
  tool_license: Settings,
};

function category(action: string): string {
  const dot = action.indexOf(".");
  return dot > 0 ? action.slice(0, dot) : "other";
}

/**
 * Verb form used in feed sentences. The audit `action` is `<resource>.<verb>`;
 * this helper renders a past-tense verb plus the noun ("submitted a job").
 *
 * Only common actions get bespoke phrasing: anything else falls back to a
 * cleaned form of the raw verb so unknown actions still surface readably.
 */
function actionPhrase(action: string, count: number = 1): {
  verb: string;
  noun: string;
} {
  const phrases: Record<string, { verb: string; noun: string }> = {
    "project.created": { verb: "created", noun: "project" },
    "project.updated": { verb: "updated", noun: "project" },
    "project.deleted": { verb: "deleted", noun: "project" },
    "target.created": { verb: "added", noun: "target" },
    "target.hotspots-updated": { verb: "updated hotspots on", noun: "target" },
    "job.submitted": { verb: "submitted a", noun: "job" },
    "job.running": { verb: "started a", noun: "job" },
    "job.succeeded": { verb: "completed a", noun: "job" },
    "job.failed": { verb: "failed a", noun: "job" },
    "job.cancelled": { verb: "cancelled a", noun: "job" },
    "design.created": { verb: "created", noun: count > 1 ? "designs" : "a design" },
    "api_key.created": { verb: "issued an", noun: "API key" },
    "api_key.rotated": { verb: "rotated an", noun: "API key" },
    "api_key.revoked": { verb: "revoked an", noun: "API key" },
    "key.created": { verb: "issued an", noun: "API key" },
    "key.rotated": { verb: "rotated an", noun: "API key" },
    "key.revoked": { verb: "revoked an", noun: "API key" },
    "member.invited": { verb: "invited", noun: "a member" },
    "member.joined": { verb: "joined", noun: "the org" },
    "member.removed": { verb: "removed", noun: "a member" },
    "member.role_changed": { verb: "changed the role of", noun: "a member" },
    "member.role-changed": { verb: "changed the role of", noun: "a member" },
    "billing.upgraded": { verb: "upgraded the", noun: "plan" },
    "billing.downgraded": { verb: "downgraded the", noun: "plan" },
    "billing.overage_recorded": { verb: "recorded an", noun: "overage" },
    "subscription.upgraded": { verb: "upgraded the", noun: "plan" },
    "subscription.downgraded": { verb: "downgraded the", noun: "plan" },
    "subscription.cancelled": { verb: "cancelled the", noun: "plan" },
    "webhook.delivered": { verb: "delivered a", noun: "webhook" },
    "webhook.failed": { verb: "failed to deliver a", noun: "webhook" },
    "webhook.created": { verb: "created a", noun: "webhook" },
    "webhook.deleted": { verb: "deleted a", noun: "webhook" },
    "webhook.secret_rotated": { verb: "rotated the secret on a", noun: "webhook" },
    "tool_license.acknowledged": {
      verb: "acknowledged a",
      noun: "tool license",
    },
    "org.created": { verb: "created the", noun: "org" },
    "org.settings_updated": { verb: "updated", noun: "org settings" },
  };
  const found = phrases[action];
  if (found) return found;
  // Fallback: strip resource prefix, replace separators.
  const dot = action.indexOf(".");
  const tail = dot > 0 ? action.slice(dot + 1) : action;
  return { verb: tail.replace(/[._-]+/g, " "), noun: "" };
}

function actorName(row: ActivityRow): string {
  if (row.actorName) return row.actorName;
  if (row.actorEmail) return row.actorEmail.split("@")[0] ?? row.actorEmail;
  if (row.userId) return row.userId.slice(0, 8);
  return "system";
}

function targetLabel(row: ActivityRow): string {
  const meta = row.metadata ?? {};
  // Prefer human-readable names from metadata.
  for (const k of ["projectName", "name", "targetName", "toolId", "label"]) {
    const v = (meta as Record<string, unknown>)[k];
    if (typeof v === "string" && v.length > 0) return v;
  }
  if (row.resourceId) return row.resourceId.slice(0, 8);
  return "";
}

function targetHref(row: ActivityRow): string | null {
  const id = row.resourceId;
  if (!id) return null;
  switch (row.resourceType) {
    case "project":
      return `/app/projects/${id}`;
    case "target":
      return `/app/targets/${id}`;
    case "job":
      return `/app/jobs/${id}`;
    case "design":
      return `/app/designs?id=${id}`;
    case "api_key":
    case "key":
      return `/app/keys`;
    case "webhook":
      return `/app/settings/webhooks`;
    case "member":
      return `/app/settings/team`;
    case "subscription":
    case "billing":
      return `/app/settings/billing`;
    default:
      return null;
  }
}

/** Relative time: "2m ago", "yesterday", "Apr 14". */
export function formatRelativeTime(d: string | Date): string {
  const date = typeof d === "string" ? new Date(d) : d;
  if (Number.isNaN(date.getTime())) return "N/A";
  const now = Date.now();
  const diffMs = now - date.getTime();
  const diffMin = Math.round(diffMs / 60_000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay === 1) return "yesterday";
  if (diffDay < 7) return `${diffDay}d ago`;
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(now - date.getTime() > 365 * 24 * 60 * 60 * 1000
      ? { year: "numeric" }
      : {}),
  });
}

interface ActivityItemProps {
  row: ActivityRow;
}

export function ActivityItem({ row }: ActivityItemProps) {
  const cat = category(row.action);
  const Icon = CATEGORY_ICON[cat] ?? Activity;
  const count = row.groupCount ?? 1;
  const { verb, noun } = actionPhrase(row.action, count);
  const href = targetHref(row);
  const label = targetLabel(row);
  const projectName = (row.metadata as Record<string, unknown> | null)?.[
    "projectName"
  ];

  const sentence = (
    <span className="font-sans text-[14px] text-ink">
      <span className="text-ink">{actorName(row)}</span>{" "}
      <span className="text-graphite">
        {count > 1 && noun ? `${verb} ${count} ${noun}` : `${verb}${noun ? ` ${noun}` : ""}`}
      </span>
      {label && (
        <>
          {" "}
          <span className="text-ink font-medium">{label}</span>
        </>
      )}
      {typeof projectName === "string" &&
        row.resourceType !== "project" &&
        projectName !== label && (
          <>
            {" "}
            <span className="text-graphite">in</span>{" "}
            <span className="text-ink">{projectName}</span>
          </>
        )}
    </span>
  );

  const inner = (
    <div className="flex items-start gap-3 py-3">
      <div
        className={cn(
          "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-lattice bg-paper",
          "group-hover:border-lattice-strong",
        )}
        data-category={cat}
        aria-hidden
      >
        <Icon className="w-4 h-4 text-graphite" />
      </div>
      <div className="min-w-0 flex-1">
        {sentence}
        <div className="mt-0.5 font-mono text-[11px] text-graphite-soft">
          {formatRelativeTime(row.createdAt)}
        </div>
      </div>
    </div>
  );

  if (href) {
    return (
      <Link
        href={href}
        className="group block rounded-lg px-3 -mx-3 hover:bg-paper-fold/60 transition-colors focus:outline-none focus:ring-2 focus:ring-ink/15"
        aria-label={`${actorName(row)} ${verb}${noun ? ` ${noun}` : ""}${label ? ` ${label}` : ""}`}
      >
        {inner}
      </Link>
    );
  }
  return <div className="px-3 -mx-3">{inner}</div>;
}

export default ActivityItem;
