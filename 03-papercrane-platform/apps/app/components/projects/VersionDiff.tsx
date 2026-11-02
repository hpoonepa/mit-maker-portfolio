"use client";

import { useMemo } from "react";

/**
 * Side-by-side diff of two project snapshots.
 *
 * Goals:
 *   - Show what changed across the four load-bearing fields (name,
 *     description, hotspots, defaultParams) without dragging in a full
 *     `diff`/`jsondiffpatch` dependency.
 *   - Be readable on small screens: stack vertically below `sm`, switch to
 *     two columns above.
 *
 * We intentionally don't render unchanged keys for `defaultParams`: a
 * project's defaults can be 30+ keys and surfacing only the deltas keeps
 * the diff legible. Identical fields collapse to a single muted "no
 * changes" line.
 */
export interface SnapshotLike {
  name: string;
  description: string | null;
  hotspots: unknown;
  defaultParams: Record<string, unknown>;
}

export interface VersionDiffProps {
  before: SnapshotLike;
  after: SnapshotLike;
}

interface ParamDelta {
  key: string;
  beforeValue: unknown;
  afterValue: unknown;
  changed: boolean;
}

export function VersionDiff({ before, after }: VersionDiffProps) {
  const nameChanged = before.name !== after.name;
  const descriptionChanged =
    (before.description ?? "") !== (after.description ?? "");

  const hotspotsChanged = useMemo(
    () => stableStringify(before.hotspots) !== stableStringify(after.hotspots),
    [before.hotspots, after.hotspots],
  );

  const paramDeltas: ParamDelta[] = useMemo(() => {
    const keys = Array.from(
      new Set([
        ...Object.keys(before.defaultParams ?? {}),
        ...Object.keys(after.defaultParams ?? {}),
      ]),
    ).sort();
    return keys.map((k) => {
      const b = before.defaultParams?.[k];
      const a = after.defaultParams?.[k];
      const changed = stableStringify(b) !== stableStringify(a);
      return { key: k, beforeValue: b, afterValue: a, changed };
    });
  }, [before.defaultParams, after.defaultParams]);

  const changedParamCount = paramDeltas.filter((d) => d.changed).length;
  const hasAnyChange =
    nameChanged ||
    descriptionChanged ||
    hotspotsChanged ||
    changedParamCount > 0;

  return (
    <div className="space-y-4" data-testid="e2e-version-diff">
      {!hasAnyChange && (
        <div className="px-5 py-4 font-sans text-[13px] text-graphite">
          No differences between this snapshot and the current state.
        </div>
      )}

      <DiffField
        label="Name"
        beforeText={before.name}
        afterText={after.name}
        changed={nameChanged}
      />

      <DiffField
        label="Description"
        beforeText={before.description ?? ""}
        afterText={after.description ?? ""}
        changed={descriptionChanged}
        multiline
      />

      <DiffField
        label="Hotspots"
        beforeText={prettyJson(before.hotspots)}
        afterText={prettyJson(after.hotspots)}
        changed={hotspotsChanged}
        multiline
      />

      <section>
        <header className="mb-2 flex items-center gap-2">
          <h4 className="font-sans text-[12px] text-graphite-soft">
            Default params
          </h4>
          {changedParamCount > 0 && (
            <span className="font-mono text-[11px] text-crane-deep">
              {changedParamCount} changed
            </span>
          )}
        </header>

        {changedParamCount === 0 ? (
          <div className="px-4 py-3 font-sans text-[13px] text-graphite">
            No parameter changes.
          </div>
        ) : (
          <ul className="space-y-2">
            {paramDeltas
              .filter((d) => d.changed)
              .map((d) => (
                <li
                  key={d.key}
                  className="grid grid-cols-1 gap-2 bg-paper px-4 py-3 sm:grid-cols-[160px_1fr_1fr] sm:items-start"
                >
                  <span className="font-mono text-[12px] text-ink">
                    {d.key}
                  </span>
                  <pre className="overflow-x-auto rounded-xl bg-crane-glow/40 px-3 py-2 font-mono text-[11px] text-crane-deep whitespace-pre-wrap break-all">
                    {prettyJson(d.beforeValue)}
                  </pre>
                  <pre className="overflow-x-auto rounded-xl bg-paper-fold/60 px-3 py-2 font-mono text-[11px] text-ink whitespace-pre-wrap break-all">
                    {prettyJson(d.afterValue)}
                  </pre>
                </li>
              ))}
          </ul>
        )}
      </section>
    </div>
  );
}

interface DiffFieldProps {
  label: string;
  beforeText: string;
  afterText: string;
  changed: boolean;
  multiline?: boolean;
}

function DiffField({
  label,
  beforeText,
  afterText,
  changed,
  multiline,
}: DiffFieldProps) {
  if (!changed) {
    return (
      <section>
        <h4 className="mb-1 font-sans text-[12px] text-graphite-soft">
          {label}
        </h4>
        <p className="font-sans text-[12px] text-graphite-soft italic">
          unchanged
        </p>
      </section>
    );
  }

  const Tag = multiline ? "pre" : "p";

  return (
    <section>
      <h4 className="mb-2 font-sans text-[12px] text-graphite-soft">
        {label}
      </h4>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <Tag className="rounded-lg border border-lattice bg-crane-glow/40 px-4 py-3 font-sans text-[13px] text-crane-deep whitespace-pre-wrap break-words">
          {beforeText || <em className="text-graphite-soft">empty</em>}
        </Tag>
        <Tag className="rounded-lg border border-lattice bg-paper px-4 py-3 font-sans text-[13px] text-ink whitespace-pre-wrap break-words">
          {afterText || <em className="text-graphite-soft">empty</em>}
        </Tag>
      </div>
    </section>
  );
}

function prettyJson(v: unknown): string {
  if (v === null || v === undefined) return "N/A";
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

/**
 * Stable JSON stringify so equality survives key reordering. Falls back to
 * `String(v)` on circular structures, which we tolerate because diff
 * accuracy isn't load-bearing for an unreachable edge case.
 */
function stableStringify(v: unknown): string {
  if (v === null || v === undefined) return "null";
  try {
    return JSON.stringify(v, sortReplacer);
  } catch {
    return String(v);
  }
}

function sortReplacer(_k: string, value: unknown): unknown {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return Object.keys(value as Record<string, unknown>)
      .sort()
      .reduce<Record<string, unknown>>((acc, k) => {
        acc[k] = (value as Record<string, unknown>)[k];
        return acc;
      }, {});
  }
  return value;
}

export default VersionDiff;
