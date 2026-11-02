"use client";

import { Menu, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { getAppUrl } from "@/lib/links";

const links = [
  { href: "#how", label: "How it works" },
  { href: "#tools", label: "Tools" },
  { href: "#benchmark", label: "Benchmark" },
  { href: "#pricing", label: "Pricing" },
  { href: "#about", label: "About" },
  { href: "#faq", label: "FAQ" },
];

export function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const appUrl = getAppUrl();
  const signInHref = `${appUrl}/login`;
  const ctaHref = `${appUrl}/app`;

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth >= 768) {
        setMenuOpen(false);
      }
    };

    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return (
    <header
      className={cn(
        "fixed top-0 left-0 right-0 z-50 transition-all duration-500",
        scrolled
          ? "bg-paper/80 backdrop-blur-xl border-b border-lattice"
          : "bg-transparent"
      )}
    >
      <div className="container-edge">
        <div className="flex items-center justify-between h-16 md:h-20">
          <Link href="/" className="flex items-center gap-2.5 group">
            <CraneMark className="w-6 h-6 text-ink transition-transform duration-700 group-hover:rotate-[8deg]" />
            <span className="font-display text-[18px] tracking-[-0.02em] font-medium lowercase">
              papercrane
            </span>
          </Link>

          <nav className="hidden md:flex items-center gap-10">
            {links.map((l) => (
              <a
                key={l.href}
                href={l.href}
                className="font-sans text-[14px] text-graphite hover:text-ink transition-colors tracking-tight"
              >
                {l.label}
              </a>
            ))}
          </nav>

          <div className="flex items-center gap-3">
            <a
              href={signInHref}
              className="hidden sm:inline font-sans text-[14px] text-graphite hover:text-ink transition-colors"
            >
              Sign in
            </a>
            <a href={ctaHref} className="hidden md:inline-flex btn-primary text-[14px] py-2 px-5">
              Start folding
              <span className="crane-dot-pulse" />
            </a>
            <button
              type="button"
              aria-label={menuOpen ? "Close navigation menu" : "Open navigation menu"}
              aria-expanded={menuOpen}
              aria-controls="mobile-nav"
              onClick={() => setMenuOpen((open) => !open)}
              className="md:hidden inline-flex items-center justify-center w-11 h-11 rounded-full border border-lattice-strong bg-paper/80 text-ink transition-colors hover:border-ink"
            >
              {menuOpen ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
            </button>
          </div>
        </div>

        <div
          id="mobile-nav"
          className={cn(
            "md:hidden overflow-hidden transition-all duration-300",
            menuOpen
              ? "max-h-[24rem] opacity-100 pb-5"
              : "max-h-0 opacity-0"
          )}
        >
          <div className="rounded-2xl border border-lattice bg-paper/95 backdrop-blur-xl px-5 py-4">
            <nav className="flex flex-col gap-1">
              {links.map((l) => (
                <a
                  key={l.href}
                  href={l.href}
                  onClick={() => setMenuOpen(false)}
                  className="rounded-xl px-3 py-3 font-sans text-[15px] text-ink transition-colors hover:bg-paper-fold"
                >
                  {l.label}
                </a>
              ))}
            </nav>

            <div className="mt-4 flex flex-col gap-3 border-t border-lattice pt-4">
              <a
                href={signInHref}
                onClick={() => setMenuOpen(false)}
                className="rounded-xl px-3 py-3 font-sans text-[15px] text-graphite transition-colors hover:bg-paper-fold hover:text-ink"
              >
                Sign in
              </a>
              <a
                href={ctaHref}
                onClick={() => setMenuOpen(false)}
                className="btn-primary justify-center"
              >
                Start folding
                <span className="crane-dot-pulse" />
              </a>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}

function CraneMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 14 L12 5 L21 14 L14 17 L12 21 L10 17 Z" />
      <path d="M12 5 L12 17" strokeOpacity="0.45" />
      <circle cx="14.2" cy="10" r="0.5" fill="#C1272D" stroke="none" />
    </svg>
  );
}
