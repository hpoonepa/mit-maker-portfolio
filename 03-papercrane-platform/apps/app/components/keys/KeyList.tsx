"use client";

import { KeyRound, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import type { ApiKeyScope } from "@papercrane/types";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import { canRevoke, canRotate, keyStatus, type KeyRecord } from "@/lib/keys/rotation";
import { ScopeBadge } from "./ScopeBadge";
import { KeyStatusPill } from "./KeyStatusPill";
import { CreateKeyModal } from "./CreateKeyModal";
import { RotateKeyDialog } from "./RotateKeyDialog";
import { RevokeKeyDialog } from "./RevokeKeyDialog";

/**
 * Top-level key management UI. Mounts:
 *   - header with "New key" affordance
 *   - empty state when the tenant has never created a key
 *   - table: Name | Prefix | Scopes | Last used | Created | Status | Actions
 *   - one-at-a-time modal state for create / rotate / revoke
 *
 * `trpc.keys.list` returns non-revoked rows; we surface them all and rely on
 * `<KeyStatusPill>` to visually differentiate active / rotating / expired.
 */
export function KeyList() {
  const query = trpc.keys.list.useQuery();

  const [creating, setCreating] = useState(false);
  const [rotatingTarget, setRotatingTarget] = useState<KeyRecord | null>(null);
  const [revokingTarget, setRevokingTarget] = useState<KeyRecord | null>(null);

  const rows = useMemo<KeyRecord[]>(() => {
    const items = query.data?.items;
    if (!Array.isArray(items)) return [];
    return items.map(coerceRow);
  }, [query.data]);

  return (
    <div className="space-y-8">
      <header className="flex items-end justify-between gap-6 flex-wrap">
        <div>
          <p className="font-sans text-[12px] text-graphite-soft">
            Authentication
          </p>
          <h1 className="mt-2 font-display text-display-md text-ink">API keys</h1>
          <p className="mt-2 max-w-xl font-sans text-[15px] text-graphite">
            Keys authenticate requests from scripts, CI, and third-party tools.
            Treat them like passwords: they&apos;re only shown once.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="btn-primary"
        >
          <Plus className="h-4 w-4" />
          New key
        </button>
      </header>

      <section className="overflow-hidden">
        {query.isLoading ? (
          <div className="px-8 py-14 text-center font-sans text-[14px] text-graphite">
            Loading…
          </div>
        ) : query.isError ? (
          <div
            role="alert"
            className="px-8 py-10 text-center font-sans text-[14px] text-crane-deep"
          >
            Failed to load keys: {query.error?.message ?? "unknown error"}
          </div>
        ) : rows.length === 0 ? (
          <EmptyState onCreate={() => setCreating(true)} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead className="bg-paper-fold">
                <tr className="text-left">
                  <Th>Name</Th>
                  <Th>Prefix</Th>
                  <Th>Scopes</Th>
                  <Th>Last used</Th>
                  <Th>Created</Th>
                  <Th>Status</Th>
                  <th className="sr-only">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((k, idx) => (
                  <KeyRow
                    key={k.id}
                    record={k}
                    divider={idx > 0}
                    onRotate={() => setRotatingTarget(k)}
                    onRevoke={() => setRevokingTarget(k)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <CreateKeyModal open={creating} onClose={() => setCreating(false)} />
      <RotateKeyDialog
        open={rotatingTarget !== null}
        target={rotatingTarget}
        onClose={() => setRotatingTarget(null)}
      />
      <RevokeKeyDialog
        open={revokingTarget !== null}
        target={revokingTarget}
        onClose={() => setRevokingTarget(null)}
      />
    </div>
  );
}

/** One row of the table + its action buttons. */
function KeyRow({
  record,
  divider,
  onRotate,
  onRevoke,
}: {
  record: KeyRecord;
  divider: boolean;
  onRotate: () => void;
  onRevoke: () => void;
}) {
  const status = keyStatus(record);
  const rotatable = canRotate(record);
  const revokable = canRevoke(record);

  return (
    <tr
      className={cn(
        "hover:bg-paper/60 transition-colors",
        divider && "border-t border-lattice",
      )}
    >
      <td className="px-5 py-3 font-sans text-[14px] text-ink">
        {record.name}
        {record.rotatedFromId && (
          <span className="ml-2 font-sans text-[12px] text-graphite-soft">
            · rotated
          </span>
        )}
      </td>
      <td className="px-5 py-3 font-mono text-[12px] text-graphite-soft">
        {maskPrefix(record.prefix)}
      </td>
      <td className="px-5 py-3">
        <div className="flex flex-wrap gap-1 max-w-xs">
          {record.scopes.map((s) => (
            <ScopeBadge key={s} scope={s} />
          ))}
        </div>
      </td>
      <td className="px-5 py-3 font-sans text-[13px] text-graphite">
        {formatDate(record.lastUsedAt) ?? <span className="text-graphite-soft">Never</span>}
      </td>
      <td className="px-5 py-3 font-sans text-[13px] text-graphite">
        {formatDate(record.createdAt) ?? "N/A"}
      </td>
      <td className="px-5 py-3">
        <KeyStatusPill k={record} />
      </td>
      <td className="px-5 py-3 text-right whitespace-nowrap">
        <div className="inline-flex items-center gap-1.5">
          <button
            type="button"
            onClick={onRotate}
            disabled={!rotatable}
            title={
              rotatable
                ? "Mint a new key, keep this one working for 24h"
                : `Cannot rotate a ${status} key`
            }
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-3 py-1.5 font-sans text-[12px] transition-colors",
              // Neutral chrome: crane red is reserved for the revoke button so
              // the destructive action stays visually unambiguous.
              rotatable
                ? "border-lattice bg-paper text-ink hover:border-ink hover:bg-paper-fold"
                : "border-lattice bg-paper-fold text-graphite-soft cursor-not-allowed",
            )}
          >
            <RefreshCw className="h-3 w-3" />
            Rotate
          </button>
          <button
            type="button"
            onClick={onRevoke}
            disabled={!revokable}
            title={revokable ? "Revoke immediately (no grace)" : "Already revoked"}
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-3 py-1.5 font-sans text-[12px] transition-colors",
              revokable
                ? "border-lattice bg-paper text-crane-deep hover:border-crane"
                : "border-lattice bg-paper-fold text-graphite-soft cursor-not-allowed",
            )}
          >
            <Trash2 className="h-3 w-3" />
            Revoke
          </button>
        </div>
      </td>
    </tr>
  );
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="px-8 py-14 text-center">
      <div className="mx-auto inline-flex h-12 w-12 items-center justify-center bg-paper">
        <KeyRound className="w-5 h-5 text-ink" />
      </div>
      <h2 className="mt-4 font-display text-[22px] text-ink">No API keys yet</h2>
      <p className="mt-2 mx-auto max-w-md font-sans text-[14px] text-graphite">
        Create one to talk to{" "}
        <code className="font-mono text-[12px]">api.papercrane.bio</code> from
        scripts or CI.
      </p>
      <button type="button" onClick={onCreate} className="btn-primary mt-6">
        <Plus className="h-4 w-4" />
        New key
      </button>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-5 py-3 font-sans text-[12px] text-graphite-soft">
      {children}
    </th>
  );
}

/**
 * Render the public key prefix as `pcr_***xxxx` so only the last 4 chars of
 * the operator-visible token leak into screenshots / DOM dumps. Server prefixes
 * are already non-secret (full secrets are never in the list payload), but
 * masking sets the right expectation: keys are credentials, treat them so.
 */
function maskPrefix(prefix: string): string {
  const tail = prefix.slice(-4);
  return `pcr_***${tail}`;
}

/**
 * Render a date-ish value as "MMM D, YYYY". Accepts Date, ISO string, or null.
 * Returns `null` for null/unparseable inputs so the caller can render a
 * fallback ("Never", "N/A").
 */
function formatDate(v: Date | string | null | undefined): string | null {
  if (!v) return null;
  const d = typeof v === "string" ? new Date(v) : v;
  if (!(d instanceof Date) || Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/**
 * Coerce whatever the tRPC client returns into a `KeyRecord`. Dates arrive
 * either as `Date` (SuperJSON) or as ISO strings (bare JSON fallback); the
 * downstream state-machine helpers handle both, but the row shape still needs
 * to be typed narrowly.
 */
function coerceRow(row: unknown): KeyRecord {
  const r = row as Record<string, unknown>;
  return {
    id: String(r.id),
    name: String(r.name),
    prefix: String(r.prefix),
    scopes: Array.isArray(r.scopes) ? (r.scopes as ApiKeyScope[]) : [],
    createdAt: (r.createdAt as Date | string) ?? new Date(0),
    lastUsedAt: (r.lastUsedAt as Date | string | null) ?? null,
    expiresAt: (r.expiresAt as Date | string | null) ?? null,
    revokedAt: (r.revokedAt as Date | string | null) ?? null,
    rotatedAt: (r.rotatedAt as Date | string | null) ?? null,
    graceExpiresAt: (r.graceExpiresAt as Date | string | null) ?? null,
    rotatedFromId: (r.rotatedFromId as string | null) ?? null,
  };
}

export default KeyList;
