"use client";

import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Toast } from "./Toast";

/**
 * Toast system: ephemeral feedback.
 *
 * The provider owns the list of active toasts and renders them into a
 * portal anchored at the bottom-right of the viewport (the spec's chosen
 * position). Individual `<Toast>` components own their own auto-dismiss
 * timer (so hover-pause works without re-renders leaking state back up).
 *
 * Max 3 visible: when a 4th toast is pushed, the oldest is evicted. This
 * keeps the stack height bounded during burst activity (e.g. a batch of
 * webhook retries landing at once).
 *
 * Context is intentionally split into two channels:
 *
 *   - `ToastApiContext` : stable `toast()` / `dismiss()` / `getActive()`
 *     handles that consumers grab through `useToast()`. Identity is
 *     stable across renders so it can be placed in effect deps safely.
 *
 *   - (internal) the provider holds the toast list as state; the API
 *     object reads it via a ref so pushing a toast does not re-render
 *     every consumer of the API context.
 */

export type ToastVariant = "success" | "error" | "info" | "warning";

export type ToastDescriptor = {
  id: string;
  title: string;
  description?: string;
  variant: ToastVariant;
  duration: number;
};

export type ToastInput = {
  title: string;
  description?: string;
  variant: ToastVariant;
  /** Override default duration in ms. */
  duration?: number;
};

export type ToastApi = {
  toast: (input: ToastInput) => string;
  dismiss: (id: string) => void;
  /** Read-only snapshot of currently visible toasts: used by tests. */
  getActive: () => ToastDescriptor[];
};

export const ToastApiContext = createContext<ToastApi | null>(null);

const MAX_VISIBLE = 3;

function defaultDuration(variant: ToastVariant): number {
  // success / info: 5s. error / warning: 8s.
  return variant === "error" || variant === "warning" ? 8000 : 5000;
}

let idCounter = 0;
function nextId(): string {
  idCounter += 1;
  return `t_${Date.now().toString(36)}_${idCounter.toString(36)}`;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastDescriptor[]>([]);
  const toastsRef = useRef<ToastDescriptor[]>([]);
  toastsRef.current = toasts;

  const push = useCallback((input: ToastInput): string => {
    const t: ToastDescriptor = {
      id: nextId(),
      title: input.title,
      description: input.description,
      variant: input.variant,
      duration: input.duration ?? defaultDuration(input.variant),
    };
    setToasts((prev) => {
      const next = [...prev, t];
      // Cap visible stack; oldest leaves first.
      return next.length > MAX_VISIBLE ? next.slice(next.length - MAX_VISIBLE) : next;
    });
    return t.id;
  }, []);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const getActive = useCallback(() => toastsRef.current, []);

  const api = useMemo<ToastApi>(
    () => ({ toast: push, dismiss, getActive }),
    [push, dismiss, getActive],
  );

  // Only mount the portal after the DOM is ready (SSR-safe).
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  return (
    <ToastApiContext.Provider value={api}>
      {children}
      {mounted &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            aria-live="polite"
            aria-atomic="false"
            className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2"
          >
            {toasts.map((t) => (
              <Toast
                key={t.id}
                id={t.id}
                title={t.title}
                description={t.description}
                variant={t.variant}
                duration={t.duration}
                onDismiss={dismiss}
              />
            ))}
          </div>,
          document.body,
        )}
    </ToastApiContext.Provider>
  );
}
