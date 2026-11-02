"use client";

import { useMemo, useState } from "react";
import { Save, RotateCcw, AlertCircle, Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { findInvalidResidues, type ChainEntry } from "@/lib/pdb/parse";
import { resolveSelected } from "@/components/targets/HotspotPicker";
import { HotspotPickerTabs } from "@/components/targets/HotspotPickerTabs";
import { ResidueList } from "@/components/targets/ResidueList";
import { trpc } from "@/lib/trpc/client";
import { mapTrpcError } from "@/lib/errors/trpc-error-map";

export type HotspotEditorProps = {
  targetId: string;
  chain: ChainEntry;
  /** Every polymer chain in the target structure. */
  targetChainIds?: string[];
  /** Author-seq ids loaded from the server (may be stale). */
  initialHotspots: number[];
  /**
   * Raw PDB or mmCIF text for the 3D tab. When absent, the Structure tab is disabled
   * and only the Sequence (2D) picker is shown. Keeps the editor usable
   * during uploads/transitions where the parsed chain is available before
   * the presigned structure URL has been resolved.
   */
  pdbText?: string;
};

const MAX_HOTSPOTS = 20;

export function HotspotEditor({
  targetId,
  chain,
  targetChainIds,
  initialHotspots,
  pdbText,
}: HotspotEditorProps) {
  // Filter out any stale residues that no longer exist in the chain. Keeps
  // the editor honest if the structure was re-uploaded.
  const initialFiltered = useMemo(
    () =>
      initialHotspots.filter((n) => !findInvalidResidues(chain, [n]).length),
    [initialHotspots, chain],
  );

  const [selected, setSelected] = useState<Set<number>>(
    () => new Set(initialFiltered),
  );
  const [savedSelection, setSavedSelection] = useState<Set<number>>(
    () => new Set(initialFiltered),
  );
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const utils = trpc.useUtils();
  const updateHotspots = trpc.targets.updateHotspots.useMutation();
  const saving = updateHotspots.isPending;

  const selectedList = useMemo(
    () => resolveSelected(chain, selected),
    [chain, selected],
  );

  const dirty = useMemo(() => {
    const a = [...selected].sort((x, y) => x - y).join(",");
    const b = [...savedSelection].sort((x, y) => x - y).join(",");
    return a !== b;
  }, [selected, savedSelection]);

  const remove = (authSeqId: number) => {
    const next = new Set(selected);
    next.delete(authSeqId);
    setSelected(next);
  };

  const clear = () => setSelected(new Set());
  const reset = () => {
    setSelected(new Set(savedSelection));
    setError(null);
  };

  const onSave = async () => {
    setError(null);

    if (selected.size > MAX_HOTSPOTS) {
      setError(`Too many hotspots: max ${MAX_HOTSPOTS}`);
      return;
    }
    const invalid = findInvalidResidues(chain, [...selected]);
    if (invalid.length > 0) {
      setError(`Residue ${invalid[0]} not found in chain ${chain.id}`);
      return;
    }

    const residues = [...selected].sort((a, b) => a - b);
    try {
      await updateHotspots.mutateAsync({
        targetId,
        hotspots: residues.length > 0 ? [{ chain: chain.id, residues }] : [],
      });
      setSavedSelection(new Set(residues));
      setSavedAt(new Date().toLocaleTimeString());
      void utils.targets.get.invalidate({ id: targetId });
      void utils.targets.list.invalidate();
    } catch (err) {
      const mapped = mapTrpcError(err, { resource: "hotspots" });
      setError(mapped.message);
    }
  };

  return (
    <section className="overflow-hidden rounded-[28px] bg-paper/70">
      <header className="flex flex-col gap-5 px-5 py-5 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
        <div className="max-w-2xl">
          <p className="font-sans text-[12px] text-crane-deep">
            Interface definition
          </p>
          <h2 className="mt-1.5 font-display text-[24px] tracking-[-0.015em] text-ink sm:text-[27px]">
            Choose binding hotspots
          </h2>
          <p className="mt-1.5 font-sans text-[13px] leading-relaxed text-graphite sm:text-[14px]">
            Mark 3–10 nearby residues on one surface. These positions tell the
            design tools where the binder should make contact.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <div
            role="status"
            className={cn(
              "inline-flex h-9 items-center gap-2 rounded-full border px-3 font-sans text-[12px]",
              dirty
                ? "border-amber-500/30 bg-amber-50 text-amber-800"
                : "border-lattice bg-paper-fold/50 text-graphite",
            )}
          >
            {dirty ? (
              <span className="h-2 w-2 rounded-full bg-current" aria-hidden />
            ) : (
              <Check className="h-3 w-3" aria-hidden />
            )}
            {dirty
              ? "Unsaved changes"
              : savedAt
                ? `Saved ${savedAt}`
                : "Up to date"}
          </div>
          <button
            type="button"
            onClick={reset}
            disabled={!dirty || saving}
            className="inline-flex h-9 items-center gap-2 rounded-md border border-lattice-strong bg-paper px-3.5 font-sans text-[12px] text-ink transition-colors hover:border-ink disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-lattice-strong"
          >
            <RotateCcw className="h-3.5 w-3.5" aria-hidden />
            Reset
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={saving || !dirty}
            className="btn-primary h-9 px-4 text-[12px] transition-colors disabled:opacity-45"
          >
            <Save className="h-3.5 w-3.5" aria-hidden />
            {saving ? "Saving…" : "Save hotspots"}
          </button>
        </div>
      </header>

      {error && (
        <div className="mx-5 mt-5 flex items-start gap-2 rounded-lg bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep sm:mx-6">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      <div className="grid min-w-0 gap-5 p-4 sm:p-6 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0">
          <HotspotPickerTabs
            chain={chain}
            targetChainIds={targetChainIds}
            pdbText={pdbText}
            selected={selected}
            onChange={setSelected}
            max={MAX_HOTSPOTS}
          />
        </div>
        <aside className="self-start xl:sticky xl:top-6">
          <ResidueList
            selected={selectedList}
            onRemove={remove}
            onClear={clear}
            max={MAX_HOTSPOTS}
          />
        </aside>
      </div>
    </section>
  );
}
