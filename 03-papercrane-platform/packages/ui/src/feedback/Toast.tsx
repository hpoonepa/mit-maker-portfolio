import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { AlertCircle, AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { cn } from "../utils/cn";

export type ToastVariant = "info" | "success" | "warning" | "error";

export interface ToastInput {
  id?: string;
  title?: ReactNode;
  description?: ReactNode;
  variant?: ToastVariant;
  /** Auto-dismiss duration in ms. Default 4500. Set 0 to persist. */
  duration?: number;
  action?: { label: string; onClick: () => void };
}

interface ToastRecord extends ToastInput {
  id: string;
}

interface ToastContextValue {
  toasts: ToastRecord[];
  addToast: (t: ToastInput) => string;
  dismissToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

/**
 * Access the toast system from any descendant of ToastProvider.
 *
 * @example
 * const { addToast } = useToast(); addToast({ title: "Saved" });
 */
export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used inside <ToastProvider>.");
  }
  return ctx;
}

export interface ToastProviderProps {
  children: ReactNode;
  /** Max concurrent toasts; older ones are dropped. Default 5. */
  max?: number;
  /** Default duration in ms. Default 4500. */
  defaultDuration?: number;
}

const ICON: Record<ToastVariant, typeof Info> = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: AlertCircle,
};

const VARIANT_STYLES: Record<ToastVariant, string> = {
  info: "border-lattice-strong text-ink",
  success: "border-lattice-strong text-ink",
  warning: "border-lattice-strong text-ink",
  error: "border-lattice-strong text-ink",
};

// Editorial accent rail (left bar): replaces colored borders with a single 3px ink-side stripe
const RAIL_STYLES: Record<ToastVariant, string> = {
  info: "before:bg-sky-600",
  success: "before:bg-emerald-600",
  warning: "before:bg-amber-600",
  error: "before:bg-crane",
};

const ICON_STYLES: Record<ToastVariant, string> = {
  info: "text-sky-700",
  success: "text-emerald-700",
  warning: "text-amber-700",
  error: "text-crane-deep",
};

function genId(): string {
  return `t-${Math.random().toString(36).slice(2, 9)}`;
}

/**
 * Global toast provider. Wrap the app once at the root.
 *
 * @example
 * <ToastProvider><App /></ToastProvider>
 */
export function ToastProvider({ children, max = 5, defaultDuration = 4500 }: ToastProviderProps) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const dismissToast = useCallback((id: string) => {
    setToasts((curr) => curr.filter((t) => t.id !== id));
    const t = timers.current.get(id);
    if (t) {
      clearTimeout(t);
      timers.current.delete(id);
    }
  }, []);

  const addToast = useCallback(
    (input: ToastInput) => {
      const id = input.id ?? genId();
      const duration = input.duration ?? defaultDuration;
      const record: ToastRecord = { ...input, id };
      setToasts((curr) => {
        const next = [...curr, record];
        return next.length > max ? next.slice(next.length - max) : next;
      });
      if (duration > 0) {
        const handle = setTimeout(() => dismissToast(id), duration);
        timers.current.set(id, handle);
      }
      return id;
    },
    [defaultDuration, max, dismissToast]
  );

  useEffect(() => {
    const current = timers.current;
    return () => {
      current.forEach((h) => clearTimeout(h));
      current.clear();
    };
  }, []);

  const value = useMemo(() => ({ toasts, addToast, dismissToast }), [toasts, addToast, dismissToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismissToast} />
    </ToastContext.Provider>
  );
}

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: ToastRecord[];
  onDismiss: (id: string) => void;
}) {
  if (typeof document === "undefined") return null;
  return createPortal(
    <div
      aria-live="polite"
      aria-atomic="false"
      className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-full max-w-sm flex-col gap-2"
    >
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>,
    document.body
  );
}

function ToastItem({ toast, onDismiss }: { toast: ToastRecord; onDismiss: (id: string) => void }) {
  const variant = toast.variant ?? "info";
  const Icon = ICON[variant];
  return (
    <div
      role={variant === "error" ? "alert" : "status"}
      className={cn(
        // Editorial toast: hairline border + grounded layered shadow + left accent rail (::before)
        "pointer-events-auto relative flex items-start gap-3 rounded-md border bg-paper pl-5 pr-4 py-3 font-sans",
        "shadow-[0_1px_0_rgba(20,17,13,0.05),0_12px_28px_-16px_rgba(20,17,13,0.35)]",
        "before:absolute before:left-0 before:top-2 before:bottom-2 before:w-[3px] before:rounded-full",
        "animate-fade-up",
        VARIANT_STYLES[variant],
        RAIL_STYLES[variant]
      )}
    >
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", ICON_STYLES[variant])} aria-hidden />
      <div className="min-w-0 flex-1 text-sm">
        {toast.title && <p className="font-semibold text-ink">{toast.title}</p>}
        {toast.description && <p className="mt-0.5 text-[0.85rem] text-graphite">{toast.description}</p>}
        {toast.action && (
          <button
            type="button"
            onClick={toast.action.onClick}
            className="mt-2 text-xs font-medium text-crane-deep hover:underline"
          >
            {toast.action.label}
          </button>
        )}
      </div>
      <button
        type="button"
        aria-label="Dismiss notification"
        onClick={() => onDismiss(toast.id)}
        className="ml-1 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded hover:bg-paper-fold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane"
      >
        <X className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}
