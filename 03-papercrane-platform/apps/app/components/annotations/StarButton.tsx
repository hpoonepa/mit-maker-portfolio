"use client";

import { Star } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";

/**
 * StarButton: toggles the caller's star for a design with optimistic
 * tRPC mutations. Used in the design detail header and the design card grid.
 */

interface Props {
  designId: string;
  starred: boolean;
  starCount?: number;
  variant?: "icon" | "label";
  className?: string;
}

export function StarButton({
  designId,
  starred,
  starCount,
  variant = "label",
  className,
}: Props) {
  const utils = trpc.useUtils();
  const star = trpc.annotations.star.useMutation({
    onMutate: async () => {
      await utils.annotations.listByDesign.cancel({ designId });
      const prev = utils.annotations.listByDesign.getData({ designId });
      if (prev) {
        utils.annotations.listByDesign.setData(
          { designId },
          { ...prev, starred: true, starCount: prev.starCount + (prev.starred ? 0 : 1) },
        );
      }
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) utils.annotations.listByDesign.setData({ designId }, ctx.prev);
    },
    onSettled: () => {
      utils.annotations.listByDesign.invalidate({ designId });
      utils.annotations.starredIds.invalidate();
    },
  });
  const unstar = trpc.annotations.unstar.useMutation({
    onMutate: async () => {
      await utils.annotations.listByDesign.cancel({ designId });
      const prev = utils.annotations.listByDesign.getData({ designId });
      if (prev) {
        utils.annotations.listByDesign.setData(
          { designId },
          {
            ...prev,
            starred: false,
            starCount: Math.max(0, prev.starCount - (prev.starred ? 1 : 0)),
          },
        );
      }
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) utils.annotations.listByDesign.setData({ designId }, ctx.prev);
    },
    onSettled: () => {
      utils.annotations.listByDesign.invalidate({ designId });
      utils.annotations.starredIds.invalidate();
    },
  });

  const busy = star.isPending || unstar.isPending;

  function toggle(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (busy) return;
    if (starred) unstar.mutate({ designId });
    else star.mutate({ designId });
  }

  if (variant === "icon") {
    return (
      <button
        type="button"
        aria-pressed={starred}
        aria-label={starred ? "Unstar design" : "Star design"}
        onClick={toggle}
        disabled={busy}
        className={cn(
          "inline-grid h-7 w-7 place-items-center rounded-full border transition-colors",
          starred
            ? "border-amber-400 bg-amber-50 text-amber-500"
            : "border-lattice bg-paper text-graphite-soft hover:text-ink",
          className,
        )}
      >
        <Star
          className={cn("h-3.5 w-3.5", starred && "fill-amber-400")}
        />
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
        "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 font-sans text-[12px] transition-colors",
        starred
          ? "border-amber-400 bg-amber-50 text-amber-700"
          : "border-lattice bg-paper text-graphite hover:text-ink",
        className,
      )}
    >
      <Star
        className={cn("h-3.5 w-3.5", starred && "fill-amber-400 text-amber-500")}
      />
      <span>{starred ? "Starred" : "Star"}</span>
      {typeof starCount === "number" && starCount > 0 && (
        <span className="font-mono text-[11px] text-graphite-soft">
          {starCount}
        </span>
      )}
    </button>
  );
}
