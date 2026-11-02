"use client";

import { createElement, useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

type RevealTag = "article" | "aside" | "div" | "li" | "section" | "span";

interface RevealProps {
  children: ReactNode;
  delay?: 0 | 1 | 2 | 3 | 4 | 5 | 6;
  className?: string;
  as?: RevealTag;
}

/**
 * Shared IntersectionObserver across every <Reveal/> mount on the page.
 * Landing has 10+ Reveals and pricing has 5+; spawning one observer each
 * was costing measurable TBT on Lighthouse. A single observer + a Map of
 * element → callback is dramatically cheaper, especially on mobile.
 *
 * Also short-circuits when the user prefers reduced motion — we mark
 * everything as seen on mount instead of animating.
 */
type RevealCallback = () => void;
let sharedObserver: IntersectionObserver | null = null;
const callbacks: WeakMap<Element, RevealCallback> = new WeakMap();

function getSharedObserver(): IntersectionObserver | null {
  if (typeof window === "undefined") return null;
  if (sharedObserver) return sharedObserver;
  sharedObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const cb = callbacks.get(entry.target);
        if (cb) {
          cb();
          callbacks.delete(entry.target);
          sharedObserver?.unobserve(entry.target);
        }
      }
    },
    { threshold: 0.12, rootMargin: "0px 0px -40px 0px" }
  );
  return sharedObserver;
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

export function Reveal({
  children,
  delay = 0,
  className,
  as: Tag = "div",
}: RevealProps) {
  const ref = useRef<HTMLElement | null>(null);
  const [seen, setSeen] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (prefersReducedMotion()) {
      setSeen(true);
      return;
    }
    const obs = getSharedObserver();
    if (!obs) {
      // Fallback for browsers without IntersectionObserver — show immediately.
      setSeen(true);
      return;
    }
    callbacks.set(el, () => setSeen(true));
    obs.observe(el);
    return () => {
      callbacks.delete(el);
      obs.unobserve(el);
    };
  }, []);

  const delayClass = delay ? `reveal-delay-${delay}` : "";

  return createElement(
    Tag,
    {
      ref: (node: Element | null) => {
        ref.current = node instanceof HTMLElement ? node : null;
      },
      className: cn("reveal", seen && "in-view", delayClass, className),
    },
    children
  );
}
