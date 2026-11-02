import { ArrowRight } from "lucide-react";
import type { ComboCard as ComboCardType } from "@papercrane/types";
import { CatalogChip } from "./CatalogChip";

/**
 * Combo card: one curated multi-stage pipeline, editorial 2-col grid item.
 *
 * Mirrors CatalogCard's visual idiom (hairline `border-t border-lattice-strong`,
 * paper bg, `font-display` name, `font-sans` tagline: no shadows/rounded chrome)
 * but is NON-interactive: combos are `coming_soon`, so this renders as a plain
 * div in a muted coming-soon state rather than a clickable Link.
 */
export function ComboCard({ combo }: { combo: ComboCardType }) {
  return (
    <div className="flex h-full flex-col justify-between bg-paper px-1 pb-8 pt-10">
      <div>
        <p className="font-sans text-[12px] text-graphite-soft">
          Pipeline · Coming soon
        </p>
        <h2 className="mt-3 font-display text-[2rem] leading-[0.98] tracking-[-0.02em] text-ink">
          {combo.name}
        </h2>
        <p className="mt-3 max-w-md font-sans text-[15px] leading-snug text-graphite">
          {combo.tagline}
        </p>
      </div>

      <div className="mt-8">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 py-2">
          {combo.stages.map((stage, i) => (
            <span key={stage} className="flex items-center gap-2">
              {i > 0 ? (
                <ArrowRight
                  aria-hidden
                  className="h-3 w-3 text-graphite-soft"
                />
              ) : null}
              <span className="font-mono text-[12px] tracking-tight text-ink">
                {stage}
              </span>
            </span>
          ))}
        </div>
        <CatalogChip label="Stages" value={String(combo.stages.length)} />
        <div className="mt-6 flex items-center gap-2 font-sans text-[12px] text-graphite-soft">
          <span>Coming soon</span>
        </div>
      </div>
    </div>
  );
}
