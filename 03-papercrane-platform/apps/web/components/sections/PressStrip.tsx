"use client";

const items = [
  "iGEM 2025 finalist team",
  "YC S26 candidate",
  "Built alongside three protein labs",
];

export function PressStrip() {
  return (
    <div className="border-y border-lattice bg-paper/40">
      <div className="container-edge py-5">
        <div className="flex flex-wrap items-center gap-x-8 gap-y-3 font-mono text-[10px] tracking-[0.2em] uppercase text-graphite-soft">
          <span className="text-graphite">From the bench</span>
          {items.map((item, i) => (
            <span key={i} className="flex items-center gap-8">
              <span className="h-px w-6 bg-lattice-strong" />
              <span>{item}</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
