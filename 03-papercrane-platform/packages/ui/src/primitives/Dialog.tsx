import {
  useCallback,
  useEffect,
  useId,
  useRef,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cn } from "../utils/cn";

export interface DialogProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: ReactNode;
  description?: ReactNode;
  /** When false, Escape key will not close the dialog. */
  closeOnEscape?: boolean;
  /** When false, clicking the backdrop will not close. */
  closeOnBackdrop?: boolean;
  /** Hide the built-in close button. */
  hideClose?: boolean;
  size?: "sm" | "md" | "lg";
  footer?: ReactNode;
}

const SIZES = {
  sm: "max-w-sm",
  md: "max-w-lg",
  lg: "max-w-2xl",
};

const FOCUSABLE =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * Accessible modal dialog with focus trap, Escape-to-close, and backdrop click.
 * Vanilla implementation: no Radix / Headless UI.
 *
 * @example
 * <Dialog open={open} onOpenChange={setOpen} title="Confirm">Body…</Dialog>
 */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  closeOnEscape = true,
  closeOnBackdrop = true,
  hideClose = false,
  size = "md",
  footer,
  className,
  children,
  ...rest
}: DialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const lastFocusedRef = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const descId = useId();

  // Save + restore focus, lock body scroll
  useEffect(() => {
    if (!open) return;
    lastFocusedRef.current = document.activeElement as HTMLElement | null;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    // Focus first focusable inside the panel
    const panel = panelRef.current;
    if (panel) {
      const focusables = panel.querySelectorAll<HTMLElement>(FOCUSABLE);
      (focusables[0] ?? panel).focus();
    }

    return () => {
      document.body.style.overflow = prevOverflow;
      lastFocusedRef.current?.focus?.();
    };
  }, [open]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (!open) return;
      if (e.key === "Escape" && closeOnEscape) {
        e.stopPropagation();
        onOpenChange(false);
        return;
      }
      if (e.key === "Tab") {
        const panel = panelRef.current;
        if (!panel) return;
        const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
          (el) => !el.hasAttribute("disabled")
        );
        if (items.length === 0) {
          e.preventDefault();
          return;
        }
        const first = items[0]!;
        const last = items[items.length - 1]!;
        const active = document.activeElement as HTMLElement | null;

        if (e.shiftKey && (active === first || !panel.contains(active))) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    },
    [open, closeOnEscape, onOpenChange]
  );

  if (!open) return null;
  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onKeyDown={handleKeyDown}
    >
      <div
        aria-hidden
        onClick={() => closeOnBackdrop && onOpenChange(false)}
        // Editorial backdrop: deeper ink wash, no blur (blur reads as shadcn-default)
        className="absolute inset-0 bg-ink/55 animate-fade-in"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        className={cn(
          // Origami panel: hairline border + grounded layered shadow (replaces shadow-2xl combo)
          "relative w-full bg-paper rounded-lg border border-lattice-strong",
          "shadow-[0_1px_0_rgba(20,17,13,0.06),0_18px_48px_-24px_rgba(20,17,13,0.45)]",
          "font-sans flex flex-col max-h-[90vh] animate-fade-up",
          SIZES[size],
          className
        )}
        {...rest}
      >
        {(title || !hideClose) && (
          <div className="flex items-start justify-between gap-4 border-b border-lattice px-5 py-4">
            <div className="min-w-0 flex-1">
              {title && (
                <h2 id={titleId} className="text-base font-semibold text-ink font-display tracking-tight">
                  {title}
                </h2>
              )}
              {description && (
                <p id={descId} className="mt-0.5 text-sm text-graphite-soft">
                  {description}
                </p>
              )}
            </div>
            {!hideClose && (
              <button
                type="button"
                aria-label="Close dialog"
                onClick={() => onOpenChange(false)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-md text-graphite hover:bg-paper-fold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            )}
          </div>
        )}
        <div className="flex-1 overflow-y-auto px-5 py-4 text-sm text-ink">{children}</div>
        {footer && (
          <div className="flex items-center justify-end gap-2 border-t border-lattice bg-paper-fold/60 px-5 py-3">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}
