"use client";

import { cn } from "@/lib/utils";
import type { ChainEntry } from "@/lib/pdb/parse";

export type ChainSelectorProps = {
  chains: ChainEntry[];
  value: string;
  onChange: (chainId: string) => void;
};

/**
 * Pill row for picking the target chain on a multi-chain structure. Shows
 * residue count per chain so users can eyeball which is the receptor vs
 * a ligand peptide without opening Mol*.
 */
export function ChainSelector({ chains, value, onChange }: ChainSelectorProps) {
  if (chains.length <= 1) return null;

  return (
    <div className="flex flex-col gap-2">
      <span className="font-sans text-[12px] text-graphite-soft">
        Target chain
      </span>
      <div className="flex flex-wrap gap-1.5">
        {chains.map((chain) => {
          const active = chain.id === value;
          return (
            <button
              key={chain.id}
              type="button"
              onClick={() => onChange(chain.id)}
              className={cn(
                "inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 font-mono text-[12px] transition-colors",
                active
                  ? "border-ink bg-ink text-paper"
                  : "border-lattice-strong bg-paper text-ink hover:border-ink",
              )}
            >
              <span className="font-semibold">{chain.id}</span>
              <span
                className={cn(
                  "text-[11px]",
                  active ? "text-paper/70" : "text-graphite-soft",
                )}
              >
                {chain.residues.length} res
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
