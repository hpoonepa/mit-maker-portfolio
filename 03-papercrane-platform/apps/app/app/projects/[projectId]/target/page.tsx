"use client";

/**
 * Target / hotspot picking page for a project.
 *
 * Wires the 3D Mol* `HotspotPicker` to a tRPC `targets.saveHotspots`
 * mutation. The page is a Client Component because the entire interaction
 * loop (click → highlight → chip → save) is client-side.
 */
import { use, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Check, Loader2, Save } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import {
  HotspotStoreProvider,
  selectionToHotspots,
  useHotspotStore,
  type Hotspot,
} from "@/lib/hotspot-store";
import { HotspotPicker } from "@/components/molstar/HotspotPicker";
import { cn } from "@/lib/utils";
import { mapTrpcError } from "@/lib/errors/trpc-error-map";

interface PageProps {
  params: Promise<{ projectId: string }>;
  searchParams?: Promise<{ pdb?: string; chain?: string }>;
}

export default function ProjectTargetPage({ params, searchParams }: PageProps) {
  const { projectId } = use(params);
  const sp = (use(
    searchParams ?? Promise.resolve({} as { pdb?: string; chain?: string }),
  ) ?? {}) as { pdb?: string; chain?: string };

  // Pre-load any persisted hotspots so the picker hydrates with them. We also
  // use this query to discover the project's current target PDB id when one
  // isn't supplied via `?pdb=`: matches the "one target per project" UX
  // the rest of the dashboard assumes (see the project detail page link).
  const initialQuery = trpc.targets.list.useQuery(
    { limit: 50 },
    { staleTime: 30_000 },
  );

  const projectTarget = useMemo(() => {
    const items = initialQuery.data?.items ?? [];
    return items.find(
      (t) => (t as { projectId?: string | null }).projectId === projectId,
    );
  }, [initialQuery.data, projectId]);

  // The list response intentionally omits signed artifact URLs. Resolve the
  // selected target through the detail endpoint so uploaded PDB/mmCIF files
  // load from storage instead of being replaced with a demo structure.
  const projectTargetId = projectTarget?.id ?? "";
  const targetDetailQuery = trpc.targets.get.useQuery(
    { id: projectTargetId },
    { enabled: projectTargetId.length > 0, staleTime: 60_000, retry: 1 },
  );
  const resolvedTarget = targetDetailQuery.data ?? projectTarget;
  const structureUrl =
    typeof resolvedTarget?.structureUrl === "string"
      ? resolvedTarget.structureUrl
      : undefined;

  // Explicit PDB deep-links still work, but a missing target stays missing:
  // we never show/save positions against an unrelated fallback protein.
  const pdbId = sp.pdb ?? resolvedTarget?.pdbId ?? undefined;

  const initial = useMemo<Hotspot[]>(() => {
    if (!resolvedTarget?.hotspots) return [];
    // `hotspots` may be a single `{chain, residues}` object (legacy seed
    // shape) or an array of those objects (current writer). Normalise to an
    // array before iterating.
    const groups = Array.isArray(resolvedTarget.hotspots)
      ? resolvedTarget.hotspots
      : [resolvedTarget.hotspots];
    const out: Hotspot[] = [];
    for (const h of groups) {
      if (!h || typeof h !== "object" || !("chain" in h) || !("residues" in h))
        continue;
      const chainId = (h as { chain: string }).chain;
      const residues = (h as { residues: number[] }).residues ?? [];
      for (const resi of residues) out.push({ chain: chainId, resi });
    }
    return out;
  }, [resolvedTarget]);

  const chain =
    sp.chain ?? resolvedTarget?.chain ?? initial[0]?.chain ?? undefined;
  const targetLabel = pdbId?.toUpperCase() ?? resolvedTarget?.name ?? "No target";
  const sourceLoading =
    initialQuery.isLoading ||
    (projectTargetId.length > 0 && targetDetailQuery.isLoading);

  return (
    <HotspotStoreProvider key={projectTargetId || "no-target"} initial={initial}>
      {/* Full-bleed shell: no centered max-w container, the HotspotPicker
          and its sequence strip occupy the full viewport width minus a
          small horizontal gutter. Header chrome compresses to leave room. */}
      <div className="flex h-screen flex-col bg-paper">
        <header className="shrink-0 border-b border-lattice px-6 py-4 sm:px-10">
          <nav
            aria-label="Breadcrumb"
            className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.08em] text-graphite-soft"
          >
            <Link
              href="/app/projects"
              className="inline-flex items-center gap-1.5 hover:text-ink transition-colors"
            >
              <ArrowLeft className="w-3 h-3" />
              Projects
            </Link>
            <span aria-hidden="true" className="text-lattice">/</span>
            <Link
              href={`/app/projects/${projectId}`}
              className="max-w-[180px] truncate normal-case tracking-normal text-graphite hover:text-ink transition-colors"
              title={projectId}
            >
              {projectId}
            </Link>
            <span aria-hidden="true" className="text-lattice">/</span>
            <span className="text-ink">Target</span>
          </nav>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between sm:gap-8">
            <div className="min-w-0">
              <h1 className="font-display text-[24px] leading-[1.1] tracking-[-0.01em] text-ink sm:text-[28px]">
                Pick binding hotspots
              </h1>
              <p className="mt-1 max-w-xl font-sans text-[13px] leading-[1.5] text-graphite">
                Click residues in the viewer or the sequence strip to mark
                contacts. Press{" "}
                <kbd className="rounded border border-lattice bg-paper-fold px-1 py-px font-mono text-[11px] text-ink">
                  h
                </kbd>{" "}
                to toggle pick mode,{" "}
                <kbd className="rounded border border-lattice bg-paper-fold px-1 py-px font-mono text-[11px] text-ink">
                  esc
                </kbd>{" "}
                to clear.
              </p>
            </div>
            <dl className="flex flex-row flex-wrap items-end gap-x-6 gap-y-1 font-mono sm:gap-x-8">
              <div className="flex flex-col gap-0.5 sm:items-end">
                <dt className="font-sans text-[10px] uppercase tracking-[0.1em] text-graphite-soft">
                  Target
                </dt>
                <dd className="text-[16px] leading-none tracking-[0.02em] text-ink">
                  {targetLabel}
                  {chain ? (
                    <span className="text-graphite"> · {chain}</span>
                  ) : null}
                </dd>
              </div>
              <div className="flex flex-col gap-0.5 sm:items-end">
                <dt className="font-sans text-[10px] uppercase tracking-[0.1em] text-graphite-soft">
                  Project
                </dt>
                <dd className="max-w-[160px] truncate text-[11px] text-graphite" title={projectId}>
                  {projectId}
                </dd>
              </div>
            </dl>
          </div>
        </header>

        {/* Viewer + sequence panel fills remaining vertical space.
            HotspotPicker owns its own internal grid; we just guarantee it
            gets the full available area to work with. */}
        <main className="min-h-0 flex-1">
          {sourceLoading ? (
            <ViewerSkeleton />
          ) : structureUrl || pdbId ? (
            <HotspotPicker
              pdbId={pdbId}
              structureUrl={structureUrl}
              targetChainIds={chain ? [chain] : undefined}
              className="h-full"
            />
          ) : (
            <MissingStructure />
          )}
        </main>

        {resolvedTarget && <SaveBar projectId={projectId} />}
      </div>
    </HotspotStoreProvider>
  );
}

function MissingStructure() {
  return (
    <div className="flex h-full min-h-[420px] items-center justify-center px-6 text-center">
      <div className="max-w-md rounded-lg border border-lattice bg-paper-fold/40 p-8">
        <h2 className="font-display text-[22px] text-ink">Add a target structure</h2>
        <p className="mt-2 font-sans text-[13px] leading-5 text-graphite">
          Upload a PDB or mmCIF target before choosing hotspots. Paper Crane will
          not substitute a different protein for missing structure data.
        </p>
        <Link href="/app/targets/new" className="btn-primary mt-5 inline-flex">
          Upload target
        </Link>
      </div>
    </div>
  );
}

/** Subtle viewer skeleton: no spinner, just a measured placeholder. */
function ViewerSkeleton() {
  return (
    <div className="flex h-full w-full items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <div className="h-24 w-24 animate-pulse rounded-full border border-lattice bg-paper-fold" />
        <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-graphite-soft">
          Loading structure
        </div>
      </div>
    </div>
  );
}

/** Bottom action bar: wires the store's selection into the tRPC mutation. */
export function SaveBar({ projectId }: { projectId: string }) {
  const store = useHotspotStore();
  const utils = trpc.useUtils?.();
  const [savedSignature, setSavedSignature] = useState(() =>
    selectionSignature(store.selection),
  );
  const pendingSignature = useRef<string | null>(null);
  const mutation = trpc.targets.saveHotspots.useMutation({
    onSuccess: () => {
      if (pendingSignature.current != null) {
        setSavedSignature(pendingSignature.current);
      }
      utils?.targets.list.invalidate?.();
      utils?.targets.get.invalidate?.();
    },
  });

  // Reset the "Saved" toast once the user mutates the selection again.
  const [savedAt, setSavedAt] = useState<number | null>(null);
  useEffect(() => {
    if (mutation.isSuccess) setSavedAt(Date.now());
  }, [mutation.isSuccess]);
  useEffect(() => {
    setSavedAt(null);
  }, [store.selection]);

  const onSave = () => {
    const hotspots = selectionToHotspots(store.selection);
    pendingSignature.current = selectionSignature(store.selection);
    mutation.mutate({ projectId, hotspots });
  };

  const count = store.selection.size;
  const currentSignature = selectionSignature(store.selection);
  const dirty = currentSignature !== savedSignature;
  const disabled = !dirty || mutation.isPending;

  return (
    <div className="shrink-0 flex flex-wrap items-center justify-between gap-3 border-t border-lattice bg-paper/95 px-6 py-3 sm:px-10">
      <div className="flex items-center gap-4 font-sans text-[13px] text-graphite">
        <span className="inline-flex items-center gap-2 font-mono tabular-nums">
          <span
            aria-hidden="true"
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              count === 0 ? "bg-graphite-soft" : "bg-crane-deep",
            )}
          />
          <strong className="font-sans text-ink">{count}</strong>
          <span className="text-[12px] uppercase tracking-[0.08em] text-graphite-soft">
            {count === 1 ? "residue" : "residues"}
          </span>
        </span>
        {mutation.error && (
          <span className="font-mono text-[12px] text-crane-deep">
            {mapTrpcError(mutation.error, { resource: "target" }).message}
          </span>
        )}
        {savedAt && !mutation.isPending && !mutation.error && (
          <span className="inline-flex items-center gap-1 text-[12px] text-graphite-soft">
            <Check className="h-3.5 w-3.5" />
            Saved
          </span>
        )}
      </div>
      <button
        type="button"
        onClick={onSave}
        disabled={disabled}
        className={cn(
          "inline-flex items-center gap-2 border px-4 py-2 font-sans text-[13px] uppercase tracking-[0.06em] transition-colors",
          disabled
            ? "cursor-not-allowed border-lattice bg-paper-fold text-graphite-soft"
            : "border-crane-deep bg-crane-deep text-paper hover:bg-ink hover:border-ink",
        )}
      >
        {mutation.isPending ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Save className="h-3.5 w-3.5" />
        )}
        Save hotspots
      </button>
    </div>
  );
}

function selectionSignature(selection: ReadonlySet<string>): string {
  return [...selection].sort().join("|");
}
