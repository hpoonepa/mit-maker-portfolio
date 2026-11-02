"use client";

/**
 * First-time-only coachmarks. Each tooltip is keyed to a `FlagKey` in
 * `lib/onboarding/seen` and is shown ONCE: dismissable. We deliberately do
 * NOT pull in a tour library (react-joyride / shepherd / driver.js): for
 * three coachmarks the manual implementation is leaner and matches our
 * design system.
 *
 * Usage:
 *   <Coachmark flag="tipNavProjects" anchor={navRef} placement="bottom">
 *     Your projects live here
 *   </Coachmark>
 *
 * The component positions itself absolutely against an anchor element using
 * its bounding rect (recomputed on resize + scroll). It renders into a portal
 * so z-index conflicts with sticky bars don't bite.
 */

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { hasSeen, markSeen, type FlagKey } from "../../lib/onboarding/seen";

type Placement = "top" | "bottom" | "left" | "right";

export interface CoachmarkProps {
  flag: FlagKey;
  /** The element to anchor the tooltip to. */
  anchor: RefObject<HTMLElement | null>;
  placement?: Placement;
  /** Override default 8px gap between anchor and tooltip. */
  offset?: number;
  children: ReactNode;
  /** Optional title rendered above `children`. */
  title?: string;
  /** Show even if previously seen: for previewing in settings. */
  forceOpen?: boolean;
}

interface Pos {
  top: number;
  left: number;
}

function computePos(rect: DOMRect, placement: Placement, gap: number, tipW: number, tipH: number): Pos {
  switch (placement) {
    case "top":
      return { top: rect.top - tipH - gap, left: rect.left + rect.width / 2 - tipW / 2 };
    case "left":
      return { top: rect.top + rect.height / 2 - tipH / 2, left: rect.left - tipW - gap };
    case "right":
      return { top: rect.top + rect.height / 2 - tipH / 2, left: rect.right + gap };
    case "bottom":
    default:
      return { top: rect.bottom + gap, left: rect.left + rect.width / 2 - tipW / 2 };
  }
}

export function Coachmark({
  flag,
  anchor,
  placement = "bottom",
  offset = 8,
  children,
  title,
  forceOpen = false,
}: CoachmarkProps) {
  const tipRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<Pos | null>(null);

  // Decide visibility on mount.
  useEffect(() => {
    if (forceOpen) {
      setOpen(true);
      return;
    }
    if (!hasSeen(flag)) {
      // Defer one frame so the anchor has a layout rect.
      const id = requestAnimationFrame(() => setOpen(true));
      return () => cancelAnimationFrame(id);
    }
  }, [flag, forceOpen]);

  // Reposition on layout + scroll + resize.
  useLayoutEffect(() => {
    if (!open) return;
    const update = () => {
      const a = anchor.current;
      const t = tipRef.current;
      if (!a || !t) return;
      const r = a.getBoundingClientRect();
      const next = computePos(r, placement, offset, t.offsetWidth, t.offsetHeight);
      // Clamp into viewport with an 8px margin.
      next.left = Math.max(8, Math.min(window.innerWidth - t.offsetWidth - 8, next.left));
      next.top = Math.max(8, Math.min(window.innerHeight - t.offsetHeight - 8, next.top));
      setPos(next);
    };
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [open, anchor, placement, offset]);

  function dismiss() {
    markSeen(flag);
    setOpen(false);
  }

  if (!open) return null;
  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      ref={tipRef}
      role="dialog"
      aria-label={title ?? "Tip"}
      style={{
        position: "fixed",
        top: pos?.top ?? -9999,
        left: pos?.left ?? -9999,
        visibility: pos ? "visible" : "hidden",
      }}
      className="z-50 max-w-xs bg-ink text-paper shadow-2xl px-3.5 py-2.5 animate-fade-up"
    >
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          {title && (
            <div className="font-display text-sm font-semibold tracking-tight mb-0.5">{title}</div>
          )}
          <div className="text-xs text-paper/85 leading-relaxed">{children}</div>
          <button
            type="button"
            onClick={dismiss}
            className="mt-2 text-xs font-medium text-crane hover:text-crane-deep focus-visible:outline-none focus-visible:underline"
          >
            Got it
          </button>
        </div>
        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss tip"
          className="-mr-1 -mt-1 inline-flex h-6 w-6 items-center justify-center rounded-md text-paper/70 hover:bg-paper/10"
        >
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>
    </div>,
    document.body,
  );
}

// ─── Pre-wired coachmarks for known anchors ──────────────────────────────────

export function NavProjectsTip({ anchor }: { anchor: RefObject<HTMLElement | null> }) {
  return (
    <Coachmark flag="tipNavProjects" anchor={anchor} placement="bottom" title="Your projects live here">
      Every target, job, and design is grouped under a project. You can rename or archive any time.
    </Coachmark>
  );
}

export function CmdKTip({ anchor }: { anchor: RefObject<HTMLElement | null> }) {
  return (
    <Coachmark flag="tipCmdK" anchor={anchor} placement="bottom" title="Press ⌘K to search anything">
      Jump to any project, target, tool, or job from anywhere in the app.
    </Coachmark>
  );
}

export function SubmitJobTip({ anchor }: { anchor: RefObject<HTMLElement | null> }) {
  return (
    <Coachmark flag="tipSubmitJob" anchor={anchor} placement="top" title="Pick tools and submit">
      Your first design is on us: 500 free seeds, no card.
    </Coachmark>
  );
}
