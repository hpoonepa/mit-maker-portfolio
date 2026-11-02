"use client";

import { Check, Minus } from "lucide-react";
import { cn } from "@/lib/utils";
import { Reveal } from "./Reveal";

type Cell = boolean | string;

const matrix: { group: string; rows: { label: string; free: Cell; pro: Cell; frontier: Cell }[] }[] = [
  {
    group: "Volume",
    rows: [
      { label: "Seeds / month included",   free: "500",       pro: "50,000",        frontier: "Unlimited (1M soft cap)" },
      { label: "Max concurrent jobs",      free: "2",         pro: "20",            frontier: "200" },
      { label: "Seats / org",              free: "1",         pro: "10 (+$50/seat)", frontier: "Unlimited" },
      { label: "Job retention",            free: "7 days",    pro: "90 days",       frontier: "365 days or custom" },
    ],
  },
  {
    group: "Tools & Compute",
    rows: [
      { label: "Open-source tools (RFdiffusion, BindCraft, Boltz-2, Chai-1, MPNN…)", free: true, pro: true, frontier: true },
      { label: "Closed-weight models (AF3-Pro, internal diffusion)", free: false, pro: false, frontier: true },
      { label: "Compute",                  free: "BYOC only", pro: "Managed A100/H100", frontier: "Dedicated cluster" },
      { label: "Top-up packs",             free: false,       pro: true,            frontier: "N/A" },
      { label: "VPC / on-prem deploy",     free: false,       pro: false,           frontier: true },
    ],
  },
  {
    group: "Support & Compliance",
    rows: [
      { label: "SLA",                      free: "—",          pro: "99.5% best-effort", frontier: "99.9% contractual" },
      { label: "Support",                  free: "Community",  pro: "Email · 24h",       frontier: "Shared Slack · 1h" },
      { label: "MSA / DPA / BAA",          free: false,        pro: "Standard ToS",      frontier: "Custom signed" },
      { label: "SOC 2 · HIPAA-eligible",   free: false,        pro: "In progress",       frontier: true },
    ],
  },
];

function CellView({ value, accent }: { value: Cell; accent?: boolean }) {
  if (value === true)
    return <Check className={cn("w-4 h-4 mx-auto", accent ? "text-crane" : "text-ink")} strokeWidth={2.2} />;
  if (value === false)
    return <Minus className="w-4 h-4 mx-auto text-graphite-soft" strokeWidth={1.5} />;
  return (
    <span className={cn("font-sans text-[13px]", accent ? "text-ink" : "text-ink-soft")}>{value}</span>
  );
}

export function PricingTable() {
  return (
    <Reveal>
      <div className="hairline-border bg-paper rounded-sm overflow-hidden">
        <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] items-end gap-2 px-6 md:px-8 pt-8 pb-5 border-b border-lattice">
          <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-graphite">
            Feature matrix
          </div>
          <div className="text-center">
            <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-graphite">Free</div>
            <div className="font-display text-[20px] mt-1">$0</div>
          </div>
          <div className="text-center bg-paper-fold rounded-sm py-2 -mb-2 relative">
            <span className="absolute -top-2 left-1/2 -translate-x-1/2 crane-dot" />
            <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-crane">Pro</div>
            <div className="font-display text-[20px] mt-1">$299<span className="text-graphite text-[12px] font-sans"> /mo</span></div>
          </div>
          <div className="text-center">
            <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-graphite">Frontier</div>
            <div className="font-display text-[20px] mt-1">$50K+<span className="text-graphite text-[12px] font-sans"> /yr</span></div>
          </div>
        </div>

        {matrix.map((g) => (
          <div key={g.group}>
            <div className="px-6 md:px-8 pt-8 pb-3 font-mono text-[10px] tracking-[0.22em] uppercase text-graphite-soft">
              {g.group}
            </div>
            {g.rows.map((r) => (
              <div
                key={r.label}
                className="grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] items-center gap-2 px-6 md:px-8 py-4 border-t border-lattice/60"
              >
                <div className="font-sans text-[14px] text-ink">{r.label}</div>
                <div className="text-center"><CellView value={r.free} /></div>
                <div className="text-center bg-paper-fold/60 py-3 -my-3"><CellView value={r.pro} accent /></div>
                <div className="text-center"><CellView value={r.frontier} /></div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </Reveal>
  );
}
