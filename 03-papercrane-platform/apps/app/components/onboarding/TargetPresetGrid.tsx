/**
 * Grid of 3 preset target cards.
 *
 * Each card shows:
 *   - target name + PDB id (mono, crane-tinted)
 *   - rationale (graphite, 1 line)
 *   - hotspot badges (lattice chip per residue)
 *
 * Selection is single-choice; the active card gets a crane ring + filled
 * dot. The grid is a `button[role=radio]` group for keyboard nav; arrow
 * keys are wired by the browser's default radiogroup behaviour when we
 * set the role.
 */
import { PRESET_TARGETS, type PresetTarget } from "@/lib/onboarding/presetTargets";

export interface TargetPresetGridProps {
  selectedId?: string | null;
  onSelect: (preset: PresetTarget) => void;
}

export function TargetPresetGrid({ selectedId, onSelect }: TargetPresetGridProps) {
  return (
    <div role="radiogroup" aria-label="Preset target" className="grid gap-3 md:grid-cols-3">
      {PRESET_TARGETS.map((p) => {
        const active = p.id === selectedId;
        return (
          <button
            key={p.id}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onSelect(p)}
            data-testid={`preset-${p.id}`}
            className={[
              "group flex flex-col items-start gap-3 rounded-lg border p-5 text-left transition-all",
              active
                ? "border-crane bg-paper"
                : "border-lattice bg-paper-fold/40 hover:border-lattice-strong hover:bg-paper",
            ].join(" ")}
          >
            <div className="flex w-full items-center justify-between">
              <span className="font-display text-lg leading-tight text-ink">
                {p.name}
              </span>
              <span
                className={[
                  "inline-block h-2.5 w-2.5 rounded-full border transition-all",
                  active ? "border-crane bg-crane" : "border-lattice-strong",
                ].join(" ")}
                aria-hidden
              />
            </div>
            <div className="font-mono text-xs text-crane-deep">
              PDB {p.pdbId} · chain {p.chain}
            </div>
            <p className="text-sm text-graphite">{p.rationale}</p>
            <div className="mt-auto flex flex-wrap gap-1.5 pt-2">
              {p.hotspots.map((h) => (
                <span
                  key={h}
                  className="rounded-full border border-lattice bg-paper px-2 py-0.5 font-mono text-[0.68rem] text-ink-soft"
                >
                  {h}
                </span>
              ))}
            </div>
          </button>
        );
      })}
    </div>
  );
}
