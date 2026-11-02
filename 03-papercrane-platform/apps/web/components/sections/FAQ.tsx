"use client";

import { useState } from "react";
import { Reveal } from "../Reveal";
import { Plus } from "lucide-react";
import { cn } from "@/lib/utils";

const qs = [
  {
    q: "How does billing work?",
    a: "Free is free forever on your own hardware. Pro is a flat monthly subscription plus metered compute (pennies per seed). Frontier is annual, invoiced, with a dedicated account manager.",
  },
  {
    q: "Which tools are supported?",
    a: "Every major open-source tool: ProteinMPNN, RFdiffusion, BindCraft, Chroma, Genie2, LigandMPNN, ESM-IF, BoltzDesign, plus validators (AF3, Boltz-2, Protenix, Chai-1). Closed partners available on Frontier.",
  },
  {
    q: "Is my target sequence private?",
    a: "Yes. On Pro, your inputs and outputs are encrypted at rest and never used for training. On Frontier we deploy into your VPC — we never see your data. Free tier runs on your own hardware, so privacy is yours.",
  },
  {
    q: "Can I add my own tool?",
    a: "Yes. Open a PR on our catalog repo with a Dockerfile and a benchmark run. We review weekly. Frontier customers get white-glove integration of proprietary tools.",
  },
  {
    q: "How secure is the platform?",
    a: "Pro and Frontier are SOC 2 Type II (in progress) and HIPAA-eligible. All traffic TLS 1.3, storage AES-256, compute in sandboxed containers. Frontier deploys within your cloud account.",
  },
  {
    q: "Do you take equity in my work?",
    a: "No. Your designs are yours. We don't own them, license them, or patent them. We're a platform, not a partner on your IP.",
  },
];

export function FAQ() {
  const [open, setOpen] = useState<number | null>(0);
  return (
    <section id="faq" className="py-section">
      <div className="container-edge">
        <Reveal>
          <div className="flex items-baseline gap-4 mb-16">
            <span className="eyebrow">§ 07 — Questions</span>
            <span className="h-px flex-1 bg-lattice" />
          </div>
        </Reveal>

        <div className="grid lg:grid-cols-12 gap-16">
          <Reveal delay={1} className="lg:col-span-4">
            <h2 className="font-display text-display-md balance leading-[0.98]">
              The answers{" "}
              <em className="italic font-normal text-graphite">to</em> the
              questions.
            </h2>
          </Reveal>

          <div className="lg:col-span-8">
            {qs.map((item, i) => {
              const isOpen = open === i;
              return (
                <Reveal
                  key={i}
                  delay={((i % 4) + 1) as 1 | 2 | 3 | 4}
                  className="border-b border-lattice-strong"
                >
                  <button
                    onClick={() => setOpen(isOpen ? null : i)}
                    className="w-full flex items-start justify-between gap-6 py-6 md:py-7 text-left group"
                  >
                    <span className="font-display text-[22px] md:text-[26px] leading-[1.15] tracking-tight pr-8">
                      {item.q}
                    </span>
                    <Plus
                      className={cn(
                        "w-5 h-5 mt-2 shrink-0 text-graphite transition-transform duration-500",
                        isOpen && "rotate-45 text-crane"
                      )}
                      strokeWidth={1.5}
                    />
                  </button>
                  <div
                    className={cn(
                      "grid transition-all duration-500 ease-out",
                      isOpen
                        ? "grid-rows-[1fr] pb-7 opacity-100"
                        : "grid-rows-[0fr] opacity-0"
                    )}
                  >
                    <div className="overflow-hidden">
                      <p className="font-sans text-[16px] leading-[1.6] text-graphite max-w-2xl">
                        {item.a}
                      </p>
                    </div>
                  </div>
                </Reveal>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
