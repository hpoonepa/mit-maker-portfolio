"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Boxes, Rows3 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ChainEntry } from "@/lib/pdb/parse";
import { HotspotPicker } from "@/components/targets/HotspotPicker";
import { HotspotPicker3D } from "@/components/targets/HotspotPicker3D";

/*
 * Tabbed container for the hotspot pickers.
 *
 * State shape
 * -----------
 * Selection state is controlled by the parent (HotspotEditor). This
 * component is purely a presenter: it chooses which picker to render and
 * persists the active tab to the URL via `?view=sequence|structure`.
 *
 *                           ┌──────────────────────┐
 *                           │   selected: Set      │
 *                           │   (owned by parent)  │
 *                           └─────────┬────────────┘
 *                                     │
 *                      ┌──────────────┴──────────────┐
 *                      │                             │
 *              ┌───────▼────────┐            ┌───────▼────────┐
 *              │  Sequence tab  │            │  Structure tab │
 *              │  HotspotPicker │            │ HotspotPicker3D│
 *              └────────────────┘            └────────────────┘
 *                   ^                                ^
 *                   └── both emit onChange/onToggle ─┘
 *                              │
 *                   URL ←─── ?view=sequence|structure
 */

export type HotspotTab = "sequence" | "structure";

export interface HotspotPickerTabsProps {
  chain: ChainEntry;
  /** Every polymer chain in the uploaded target; none are binders yet. */
  targetChainIds?: string[];
  /** Raw PDB text for the 3D viewer. If omitted, structure tab is disabled. */
  pdbText?: string;
  selected: Set<number>;
  onChange: (next: Set<number>) => void;
  max?: number;
  /** Optional initial tab (falls back to ?view= or "sequence"). */
  initialTab?: HotspotTab;
  /** Persist the active tab to `?view=`. Defaults to true. */
  syncToUrl?: boolean;
}

const TABS: Array<{ id: HotspotTab; label: string; icon: React.ComponentType<{ className?: string }> }> = [
  { id: "sequence", label: "Sequence", icon: Rows3 },
  { id: "structure", label: "Structure", icon: Boxes },
];

export function HotspotPickerTabs({
  chain,
  targetChainIds,
  pdbText,
  selected,
  onChange,
  max = 20,
  initialTab,
  syncToUrl = true,
}: HotspotPickerTabsProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const urlTab = readTab(searchParams?.get("view"));
  const [tab, setTab] = useState<HotspotTab>(initialTab ?? urlTab ?? "sequence");

  // Keep the URL in sync with the active tab. Use replaceState so each tab
  // flip does not pollute the back-button history.
  useEffect(() => {
    if (!syncToUrl || !pathname) return;
    const current = readTab(searchParams?.get("view")) ?? "sequence";
    if (current === tab) return;
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    params.set("view", tab);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }, [tab, pathname, router, searchParams, syncToUrl]);

  // If the URL changes externally, adopt it.
  useEffect(() => {
    if (!syncToUrl) return;
    const fromUrl = readTab(searchParams?.get("view"));
    if (fromUrl && fromUrl !== tab) setTab(fromUrl);
    // We intentionally do not list `tab` in the dep array: only URL drives
    // an update here. A tab click goes the other way (effect above).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, syncToUrl]);

  const atCap = selected.size >= max;
  const structureDisabled = !pdbText;
  const targetChainCount = targetChainIds?.length ?? 1;

  // Keep the residue ID list stable for the 3D picker: it uses this for
  // arrow-key focus nav.
  const residueIds = useMemo(
    () => chain.residues.map((r) => r.authSeqId),
    [chain.residues],
  );

  const toggleFrom3D = useCallback(
    (resi: number) => {
      const next = new Set(selected);
      if (next.has(resi)) {
        next.delete(resi);
      } else {
        if (next.size >= max) return; // cap enforced by picker UI too
        next.add(resi);
      }
      onChange(next);
    },
    [max, onChange, selected],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <nav
          role="tablist"
          aria-label="Hotspot picker view"
          className="inline-flex w-fit items-center gap-1 rounded-xl border border-lattice bg-paper-fold/70 p-1"
        >
          {TABS.map(({ id, label, icon: Icon }) => {
            const active = tab === id;
            const disabled = id === "structure" && structureDisabled;
            return (
              <button
                key={id}
                type="button"
                role="tab"
                id={`hotspot-tab-${id}`}
                aria-selected={active}
                aria-controls={`hotspot-panel-${id}`}
                aria-disabled={disabled || undefined}
                disabled={disabled}
                onClick={() => !disabled && setTab(id)}
                className={cn(
                  "inline-flex h-9 items-center gap-2 rounded-lg px-3.5 font-sans text-[12px] transition-all",
                  active
                    ? "bg-paper text-ink"
                    : "text-graphite hover:bg-paper/50 hover:text-ink",
                  disabled && "cursor-not-allowed opacity-50 hover:bg-transparent hover:text-graphite",
                )}
                title={
                  disabled
                    ? "Structure unavailable: upload a PDB to enable"
                    : undefined
                }
              >
                <Icon className="h-3.5 w-3.5" aria-hidden />
                {label}
              </button>
            );
          })}
        </nav>

        <div className="flex flex-wrap items-center gap-2 font-sans text-[12px]">
          <span className="inline-flex h-8 items-center gap-2 rounded-full border border-lattice bg-paper px-3 text-graphite">
            <span className="h-1.5 w-1.5 rounded-full bg-graphite" aria-hidden />
            Target only · {targetChainCount}{" "}
            {targetChainCount === 1 ? "chain" : "chains"}
          </span>
          <span className="inline-flex h-8 items-center rounded-full bg-ink px-3 text-paper">
            Editing chain {chain.id}
          </span>
        </div>
      </div>

      <div
        role="tabpanel"
        id="hotspot-panel-sequence"
        aria-labelledby="hotspot-tab-sequence"
        hidden={tab !== "sequence"}
      >
        {tab === "sequence" && (
          <HotspotPicker
            chain={chain}
            selected={selected}
            onChange={onChange}
            max={max}
          />
        )}
      </div>

      <div
        role="tabpanel"
        id="hotspot-panel-structure"
        aria-labelledby="hotspot-tab-structure"
        hidden={tab !== "structure"}
      >
        {tab === "structure" && pdbText && (
          <HotspotPicker3D
            pdbText={pdbText}
            chainId={chain.id}
            targetChainIds={targetChainIds}
            selected={selected}
            onToggle={toggleFrom3D}
            atCap={atCap}
            residues={residueIds}
          />
        )}
      </div>
    </div>
  );
}

function readTab(raw: string | null | undefined): HotspotTab | null {
  if (raw === "sequence" || raw === "structure") return raw;
  return null;
}
