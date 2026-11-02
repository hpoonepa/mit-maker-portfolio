"use client";

import { CheckCircle2, AlertTriangle, AlertCircle, Info, X } from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactElement,
} from "react";
import type { ToastVariant } from "./ToastProvider";

/**
 * Individual toast card.
 *
 * The component owns its own auto-dismiss timer so hover-to-pause can be
 * implemented without funneling all timer bookkeeping through the
 * provider (which would re-render every toast on each tick).
 *
 * Interaction:
 *   - click the × button       → dismiss
 *   - click the toast body     → dismiss (desktop)
 *   - swipe right on touch     → dismiss (touch)
 *   - hover                    → pause timer; resume on leave
 */

type ToastProps = {
  id: string;
  title: string;
  description?: string;
  variant: ToastVariant;
  duration: number;
  onDismiss: (id: string) => void;
};

// On-brand toast palette: hairline border + 2px left rail (Crane red for
// error, ink for info, emerald for success, amber for warning). No drop
// shadow, no gradient: keeps toasts feeling like part of the paper UI.
const VARIANT_STYLES: Record<
  ToastVariant,
  { rail: string; fg: string; bg: string; iconNode: ReactElement }
> = {
  success: {
    rail: "border-l-emerald-600",
    fg: "text-emerald-900",
    bg: "bg-paper",
    iconNode: <CheckCircle2 className="h-4 w-4 text-emerald-600" aria-hidden />,
  },
  error: {
    rail: "border-l-crane",
    fg: "text-ink",
    bg: "bg-paper",
    iconNode: <AlertCircle className="h-4 w-4 text-crane" aria-hidden />,
  },
  warning: {
    rail: "border-l-amber-600",
    fg: "text-ink",
    bg: "bg-paper",
    iconNode: <AlertTriangle className="h-4 w-4 text-amber-600" aria-hidden />,
  },
  info: {
    rail: "border-l-ink",
    fg: "text-ink",
    bg: "bg-paper",
    iconNode: <Info className="h-4 w-4 text-graphite" aria-hidden />,
  },
};

const SWIPE_DISMISS_PX = 80;

export function Toast({
  id,
  title,
  description,
  variant,
  duration,
  onDismiss,
}: ToastProps) {
  // Remaining time (ms) tracked explicitly so hover-pause can freeze the
  // countdown without losing elapsed progress.
  const remainingRef = useRef(duration);
  const startRef = useRef(Date.now());
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [dragX, setDragX] = useState(0);
  const dragStartRef = useRef<number | null>(null);

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const schedule = (ms: number) => {
    clearTimer();
    startRef.current = Date.now();
    timerRef.current = setTimeout(() => onDismiss(id), ms);
  };

  useEffect(() => {
    schedule(remainingRef.current);
    return clearTimer;
    // Deliberately depend only on `id`: mount-once lifecycle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const pause = () => {
    if (!timerRef.current) return;
    const elapsed = Date.now() - startRef.current;
    remainingRef.current = Math.max(0, remainingRef.current - elapsed);
    clearTimer();
  };

  const resume = () => {
    if (timerRef.current) return;
    if (remainingRef.current <= 0) {
      onDismiss(id);
      return;
    }
    schedule(remainingRef.current);
  };

  // Touch swipe-to-dismiss (right swipe only, keeps it simple).
  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.pointerType !== "touch") return;
    dragStartRef.current = e.clientX;
    pause();
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (dragStartRef.current == null) return;
    const dx = Math.max(0, e.clientX - dragStartRef.current);
    setDragX(dx);
  };
  const onPointerUp = () => {
    if (dragStartRef.current == null) return;
    const committed = dragX >= SWIPE_DISMISS_PX;
    dragStartRef.current = null;
    setDragX(0);
    if (committed) {
      onDismiss(id);
    } else {
      resume();
    }
  };

  const style = VARIANT_STYLES[variant];
  const translateX = dragX ? `translateX(${dragX}px)` : undefined;
  const opacity = dragX ? String(Math.max(0, 1 - dragX / 200)) : undefined;

  return (
    <div
      role="status"
      data-variant={variant}
      data-toast-id={id}
      className={`pointer-events-auto flex items-start gap-3 rounded-xl border border-lattice border-l-2 p-3 font-sans text-[13px] transition-transform ${style.bg} ${style.fg} ${style.rail}`}
      style={{ transform: translateX, opacity }}
      onMouseEnter={pause}
      onMouseLeave={resume}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    >
      <div className="mt-0.5 shrink-0">{style.iconNode}</div>
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{title}</div>
        {description && (
          <div className="mt-0.5 font-mono text-[12px] text-graphite">
            {description}
          </div>
        )}
      </div>
      <button
        type="button"
        aria-label="Dismiss notification"
        onClick={() => onDismiss(id)}
        className="shrink-0 rounded-md p-1 text-graphite-soft hover:bg-paper-fold hover:text-ink"
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}
