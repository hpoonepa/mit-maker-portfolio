"use client";

import Link from "next/link";
import { use, useEffect, useMemo, useState } from "react";
import { ArrowLeft, AlertCircle, Loader2 } from "lucide-react";
import type { Hotspot } from "@papercrane/types";
import { trpc } from "@/lib/trpc/client";
import { TargetSummary } from "@/components/targets/TargetSummary";
import { HotspotEditor } from "@/components/targets/HotspotEditor";
import {
  parseStructure,
  largestChain,
  type ChainEntry,
} from "@/lib/pdb/parse";
import {
  fetchTargetStructure,
  targetStructureSources,
} from "@/lib/pdb/fetchTargetStructure";

/**
 * Target detail + hotspot editor.
 *
 * Client component: we need to fetch the raw PDB text from RCSB so the
 * Structure tab in <HotspotEditor> can render Mol*. Doing this in a server
 * component would force the PDB through the Next runtime on every nav,
 * inflate the RSC payload, and lose the in-memory cache. Instead the page
 * uses tRPC's React Query hook for the target row and a `fetch()` against
 * the RCSB CDN for the structure file.
 *
 *   ┌─────────────┐    target row (id, pdbId, chain, hotspots, ...)
 *   │ trpc.targets│──────────────────────┐
 *   │   .get      │                      │
 *   └─────────────┘                      ▼
 *   ┌─────────────┐               ┌──────────────┐
 *   │ RCSB CDN    │── pdbText ──▶ │ HotspotEditor│
 *   └─────────────┘               └──────────────┘
 */
export default function TargetDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  const targetQuery = trpc.targets.get.useQuery(
    { id },
    { staleTime: 60_000, retry: 1 },
  );

  const target = targetQuery.data;
  const loadedTargetId = target?.id;

  const pdbId = (target?.pdbId ?? null) as string | null;
  const structureUrl =
    typeof target?.structureUrl === "string" ? target.structureUrl : null;

  const storedHotspots = useMemo(() => {
    const raw = target?.hotspots;
    if (!raw) return [] as Hotspot[];
    return Array.isArray(raw) ? (raw as Hotspot[]) : [raw as Hotspot];
  }, [target?.hotspots]);
  const storedChain =
    typeof target?.chain === "string"
      ? target.chain
      : storedHotspots[0]?.chain ?? null;

  const [pdbText, setPdbText] = useState<string | null>(null);
  const [pdbError, setPdbError] = useState<string | null>(null);
  const [pdbLoading, setPdbLoading] = useState(false);

  // Fetch the raw PDB text once we know the id. AbortController guards
  // against rapid id changes (back/forward nav) producing stale state.
  useEffect(() => {
    if (!loadedTargetId) return;
    const sources = targetStructureSources(structureUrl, pdbId);
    if (sources.length === 0) {
      setPdbText(null);
      setPdbError(null);
      setPdbLoading(false);
      return;
    }

    const ctrl = new AbortController();
    setPdbLoading(true);
    setPdbError(null);
    setPdbText(null);

    (async () => {
      try {
        const text = await fetchTargetStructure(sources, ctrl.signal);
        setPdbText(text);
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        setPdbError(
          err instanceof Error ? err.message : "Could not fetch structure",
        );
      } finally {
        if (!ctrl.signal.aborted) setPdbLoading(false);
      }
    })();

    return () => ctrl.abort();
  }, [loadedTargetId, structureUrl, pdbId]);

  const parsedStructure = useMemo(() => {
    if (!pdbText) return null;
    try {
      return parseStructure(pdbText);
    } catch {
      return null;
    }
  }, [pdbText]);

  // Prefer the previously saved chain. For older targets without one, use
  // the largest polymer chain rather than assuming chain A.
  const chain: ChainEntry | null = useMemo(() => {
    if (!parsedStructure) return null;
    const match = storedChain
      ? parsedStructure.chains.find((candidate) => candidate.id === storedChain)
      : null;
    return match ?? largestChain(parsedStructure);
  }, [parsedStructure, storedChain]);

  const activeChainId = chain?.id ?? storedChain;
  const targetChainIds = useMemo(
    () => parsedStructure?.chains.map((candidate) => candidate.id) ?? [],
    [parsedStructure],
  );

  // Hotspots from the DB are stored as Hotspot[] (chain + residues[]).
  // Flatten the residues for the picked chain into a flat array of
  // author-seq ids, which is what HotspotEditor consumes.
  const initialHotspots = useMemo(() => {
    if (!activeChainId) return [] as number[];
    const matching = storedHotspots.filter(
      (h) => !h?.chain || h.chain === activeChainId,
    );
    const ids = matching.flatMap((h) => h.residues ?? []);
    return Array.from(new Set(ids)).sort((a, b) => a - b);
  }, [storedHotspots, activeChainId]);

  if (targetQuery.isLoading) {
    return <SkeletonPage />;
  }

  if (targetQuery.error || !target) {
    return (
      <ErrorPage
        title="Target not found"
        message={
          targetQuery.error?.message ??
          "We couldn't load this target. It may have been deleted or you may not have access."
        }
      />
    );
  }

  const residueCount = chain?.residues.length ?? 0;
  const formattedCreatedAt = formatRelative(target.createdAt);

  return (
    <div className="space-y-8">
      <div>
        <Link
          href="/app/targets"
          className="inline-flex items-center gap-2 font-sans text-[13px] text-graphite hover:text-ink transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          All targets
        </Link>
      </div>

      <TargetSummary
        name={target.name}
        pdbId={target.pdbId ?? null}
        chain={activeChainId ?? "N/A"}
        residueCount={residueCount}
        chainCount={parsedStructure?.chains.length ?? 0}
        uploadedAt={formattedCreatedAt}
      />

      {!structureUrl && !pdbId && (
        <Notice
          tone="warn"
          message="No structure file is attached to this target. Hotspot editing is disabled so we never save positions against the wrong protein."
        />
      )}

      {pdbError && (
        <Notice
          tone="error"
          message={`Couldn't load structure (${pdbError}). The Sequence tab still works.`}
        />
      )}

      {pdbLoading && !chain && (
        <div className="flex items-center gap-2 font-sans text-[13px] text-graphite">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          Loading target structure…
        </div>
      )}

      {chain ? (
        <HotspotEditor
          targetId={id}
          chain={chain}
          targetChainIds={targetChainIds}
          initialHotspots={initialHotspots}
          pdbText={pdbText ?? undefined}
        />
      ) : pdbText && !pdbLoading ? (
        <Notice
          tone="error"
          message="The downloaded file did not contain a readable protein chain. Check the structure and upload a valid PDB or mmCIF file."
        />
      ) : null}
    </div>
  );
}

function SkeletonPage() {
  return (
    <div className="space-y-10 animate-pulse">
      <div className="h-4 w-24 rounded bg-lattice/60" />
      <div className="h-32" />
      <div className="h-64" />
    </div>
  );
}

function ErrorPage({ title, message }: { title: string; message: string }) {
  return (
    <div className="space-y-6">
      <Link
        href="/app/targets"
        className="inline-flex items-center gap-2 font-sans text-[13px] text-graphite hover:text-ink transition-colors"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        All targets
      </Link>
      <div className="p-8">
        <div className="flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-crane-deep mt-0.5 shrink-0" />
          <div>
            <h2 className="font-display text-[22px] text-ink">{title}</h2>
            <p className="mt-2 font-sans text-[14px] text-graphite">{message}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function Notice({
  tone,
  message,
}: {
  tone: "warn" | "error";
  message: string;
}) {
  return (
    <div
      className={
        tone === "error"
          ? "flex items-start gap-2 rounded-lg bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep"
          : "flex items-start gap-2 px-4 py-3 font-sans text-[13px] text-graphite"
      }
    >
      <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
      <span>{message}</span>
    </div>
  );
}

function formatRelative(value: string | Date | undefined): string | undefined {
  if (!value) return undefined;
  const then = typeof value === "string" ? new Date(value) : value;
  const ms = Date.now() - then.getTime();
  if (!Number.isFinite(ms) || ms < 0) return undefined;
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}
