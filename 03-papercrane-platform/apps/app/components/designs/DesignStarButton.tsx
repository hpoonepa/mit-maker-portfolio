"use client";

import { Star } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";

/**
 * DesignStarButton: design-row + design-detail action-bar star toggle.
 *
 * Optimistic via the `annotations.starredIds` cache (the list-page source
 * of truth). The detail page's `annotations.listByDesign` is invalidated
 * onSettled so the comments header re-syncs `{ starred, starCount }`.
 *
 * Visual: filled crane-red star when active, ghost outline when inactive.
 * Mono label reads "Starred" / "Star".
 */

interface Props {
  designId: string;
  /**
   * Optional override for starred state. When omitted the component reads
   * from the `annotations.starredIds` cache. Pass when the parent already
   * has the value to avoid an extra render after first paint.
   */
  starred?: boolean;
  size?: "sm" | "md";
  /** Hide the text label and render a compact icon-only chip. */
  iconOnly?: boolean;
  className?: string;
  /** Stop the click from bubbling into a parent <Link>/<button>. */
  stopPropagation?: boolean;
}

export function DesignStarButton({
  designId,
  starred: starredProp,
  size = "md",
  iconOnly = false,
  className,
  stopPropagation = true,
}: Props) {
  const utils = trpc.useUtils();
  const starredIdsQuery = trpc.annotations.starredIds.useQuery(undefined, {
    // The list page already mounts this query; we just consume the cache.
    staleTime: 30_000,
  });

  const starredFromCache = (starredIdsQuery.data?.ids ?? []).includes(designId);
  const starred = starredProp ?? starredFromCache;

  function applyOptimistic(nextStarred: boolean) {
    const prev = utils.annotations.starredIds.getData();
    if (!prev) return { prev };
    const set = new Set(prev.ids);
    if (nextStarred) set.add(designId);
    else set.delete(designId);
    utils.annotations.starredIds.setData(undefined, { ids: Array.from(set) });
    return { prev };
  }

  const star = trpc.annotations.star.useMutation({
    onMutate: async () => {
      await utils.annotations.starredIds.cancel();
      return applyOptimistic(true);
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) utils.annotations.starredIds.setData(undefined, ctx.prev);
    },
    onSettled: () => {
      utils.annotations.starredIds.invalidate();
      utils.annotations.listByDesign.invalidate({ designId });
    },
  });

  const unstar = trpc.annotations.unstar.useMutation({
    onMutate: async () => {
      await utils.annotations.starredIds.cancel();
      return applyOptimistic(false);
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) utils.annotations.starredIds.setData(undefined, ctx.prev);
    },
    onSettled: () => {
      utils.annotations.starredIds.invalidate();
      utils.annotations.listByDesign.invalidate({ designId });
    },
  });

  const busy = star.isPending || unstar.isPending;

  function toggle(e: React.MouseEvent) {
    if (stopPropagation) {
      e.preventDefault();
      e.stopPropagation();
    }
    if (busy) return;
    if (starred) unstar.mutate({ designId });
    else star.mutate({ designId });
  }

  const iconCls = cn(
    size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5",
    starred && "fill-crane-red text-crane-red",
  );

  if (iconOnly) {
    return (
      <button
        type="button"
        aria-pressed={starred}
        aria-label={starred ? "Unstar design" : "Star design"}
        onClick={toggle}
        disabled={busy}
        className={cn(
          "inline-grid place-items-center rounded-full border transition-colors",
          size === "sm" ? "h-6 w-6" : "h-7 w-7",
          starred
            ? "border-crane-red bg-crane-red/10 text-crane-red"
            : "border-lattice bg-paper text-graphite-soft hover:text-ink",
          busy && "opacity-60",
          className,
        )}
      >
        <Star className={iconCls} />
      </button>
    );
  }

  return (
    <button
      type="button"
      aria-pressed={starred}
      onClick={toggle}
      disabled={busy}
      className={cn(
        "inline-flex items-center gap-2 rounded-full border font-sans transition-colors",
        size === "sm"
          ? "px-2.5 py-1 text-[10px]"
          : "px-3 py-1.5 text-[11px]",
        starred
          ? "border-crane-red bg-crane-red/10 text-crane-red"
          : "border-lattice bg-paper text-graphite hover:text-ink",
        busy && "opacity-60",
        className,
      )}
    >
      <Star className={iconCls} />
      <span>{starred ? "Starred" : "Star"}</span>
    </button>
  );
}

export default DesignStarButton;
