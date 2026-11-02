"use client";

import { FormEvent, useState } from "react";
import { Reveal } from "../Reveal";
import { ArrowUpRight } from "lucide-react";

export function CTA() {
  const [email, setEmail] = useState("");

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const subject = encodeURIComponent("Paper Crane beta access");
    const body = encodeURIComponent(
      `Please add me to the Paper Crane waitlist.\n\nEmail: ${email}`
    );

    window.location.href = `mailto:hello@papercrane.bio?subject=${subject}&body=${body}`;
  };

  return (
    <section id="cta" className="py-section">
      <div className="container-edge">
        <Reveal>
          <div className="relative bg-ink text-paper rounded-sm overflow-hidden px-8 py-20 md:px-16 md:py-32">
            {/* Grain */}
            <div
              className="absolute inset-0 pointer-events-none opacity-[0.08]"
              style={{
                backgroundImage:
                  "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 400 400' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0.6 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
              }}
            />

            {/* Massive crane silhouette background */}
            <svg
              className="absolute -right-20 -top-20 w-[520px] h-[520px] opacity-[0.05] pointer-events-none"
              viewBox="0 0 420 420"
              fill="currentColor"
            >
              <path d="M 80 220 L 150 190 L 170 230 L 110 255 Z M 90 180 L 210 100 L 210 260 L 150 270 L 110 240 Z M 210 100 L 340 170 L 320 230 L 240 260 L 210 260 Z M 210 100 L 255 60 L 270 70 L 225 115 Z M 270 70 L 290 63 L 272 76 Z" />
            </svg>

            <div className="relative grid lg:grid-cols-12 gap-10 items-end">
              <div className="lg:col-span-8">
                <div className="flex items-center gap-3 mb-8">
                  <span className="crane-dot-pulse" />
                  <span className="font-mono text-[10px] tracking-[0.24em] uppercase text-paper/50">
                    Private beta opening · Spring 2026
                  </span>
                </div>

                <h2 className="font-display text-display-lg balance leading-[0.95]">
                  A thousand seeds.{" "}
                  <em className="italic font-normal text-paper/60">
                    One binder.
                  </em>
                  <br />
                  Start folding.
                </h2>

                <p className="mt-8 text-[17px] leading-[1.55] text-paper/70 max-w-lg font-sans">
                  Join the iGEM teams, academic labs, and biotechs already on
                  the waitlist. No credit card. Free forever on your hardware.
                </p>
              </div>

              <div className="lg:col-span-4">
                <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
                  <label htmlFor="waitlist-email" className="sr-only">
                    Email address
                  </label>
                  <input
                    id="waitlist-email"
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="your@email.com"
                    autoComplete="email"
                    required
                    className="w-full rounded-sm border border-paper/20 bg-paper/5 px-4 py-3.5 text-paper placeholder:text-paper/45 font-sans text-[16px] focus:outline-none focus:border-crane focus:bg-paper/8 transition-colors"
                  />
                  <button
                    type="submit"
                    className="mt-3 inline-flex items-center justify-center gap-2 bg-crane text-paper rounded-full py-3.5 font-sans text-[15px] tracking-tight hover:bg-paper hover:text-ink transition-all group"
                  >
                    Request access
                    <ArrowUpRight
                      className="w-4 h-4 group-hover:-translate-y-0.5 group-hover:translate-x-0.5 transition-transform duration-300"
                      strokeWidth={1.8}
                    />
                  </button>
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2 font-mono text-[10px] tracking-[0.2em] uppercase text-paper/40">
                    <span>Opens your email client</span>
                    <span className="hidden sm:inline">·</span>
                    <a
                      href="mailto:hello@papercrane.bio?subject=Paper%20Crane%20beta%20access"
                      className="text-paper/65 transition-colors hover:text-paper"
                    >
                      hello@papercrane.bio
                    </a>
                  </div>
                </form>
              </div>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
