import { cn } from "@/lib/utils";

type UsageMeterProps = {
  /** Seeds consumed this period. */
  consumed: number;
  /** Seeds included in current plan. */
  included: number;
  /** Optional className for the root element. */
  className?: string;
  /** Display size. `compact` is for the topbar; `full` for the usage page. */
  size?: "compact" | "full";
  /** Optional label; defaults to "Seeds". */
  label?: string;
};

/**
 * SVG ring chart showing seed consumption vs plan quota. No deps: pure
 * Tailwind + inline SVG. Sized 20px (compact) or 96px (full).
 */
export function UsageMeter({
  consumed,
  included,
  className,
  size = "compact",
  label = "Seeds",
}: UsageMeterProps) {
  const pct = included > 0 ? Math.min(consumed / included, 1) : 0;
  const overage = Math.max(consumed - included, 0);

  const radius = size === "compact" ? 9 : 42;
  const stroke = size === "compact" ? 2.5 : 8;
  const viewBox = (radius + stroke) * 2;
  const circ = 2 * Math.PI * radius;
  const dash = pct * circ;

  const warning = pct >= 0.85;
  const ringColor = overage > 0
    ? "stroke-crane"
    : warning
      ? "stroke-crane"
      : "stroke-ink";

  return (
    <div
      className={cn(
        size === "compact"
          ? "flex items-center gap-2"
          : "flex items-center gap-5",
        className
      )}
    >
      <svg
        width={viewBox}
        height={viewBox}
        viewBox={`0 0 ${viewBox} ${viewBox}`}
        aria-hidden="true"
        className="shrink-0"
      >
        <circle
          cx={viewBox / 2}
          cy={viewBox / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          className="stroke-lattice"
        />
        <circle
          cx={viewBox / 2}
          cy={viewBox / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circ}`}
          transform={`rotate(-90 ${viewBox / 2} ${viewBox / 2})`}
          className={cn("transition-[stroke-dasharray] duration-500", ringColor)}
        />
      </svg>

      {size === "compact" ? (
        <div className="leading-tight">
          <div className="font-sans tabular-nums text-[12px] text-ink">
            {formatCount(consumed)}
            <span className="text-graphite-soft"> / {formatCount(included)}</span>
          </div>
          <div className="font-sans text-[12px] text-graphite-soft">
            {label}
          </div>
        </div>
      ) : (
        <div>
          <div className="font-sans text-[12px] text-graphite-soft">
            {label} this period
          </div>
          <div className="mt-1.5 font-sans tabular-nums text-[34px] leading-none tracking-[-0.02em] text-ink tabular-nums">
            {formatCount(consumed)}
            <span className="ml-1 font-sans tabular-nums text-[15px] text-graphite-soft">
              / {formatCount(included)}
            </span>
          </div>
          {overage > 0 && (
            <div className="mt-1 font-sans text-[13px] text-crane-deep">
              {formatCount(overage)} over plan: overage billing active.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1).replace(/\.0$/, "") + "k";
  return n.toString();
}
