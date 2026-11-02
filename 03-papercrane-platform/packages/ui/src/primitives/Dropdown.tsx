import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type KeyboardEvent,
} from "react";
import { cn } from "../utils/cn";

export interface DropdownItem {
  id: string;
  label: ReactNode;
  icon?: ReactNode;
  onSelect?: () => void;
  disabled?: boolean;
  danger?: boolean;
}

export interface DropdownProps {
  /** Trigger rendered as-is; Dropdown binds its own click + aria. */
  trigger: (props: {
    open: boolean;
    toggle: () => void;
    ref: React.RefObject<HTMLButtonElement | null>;
  }) => ReactNode;
  items: DropdownItem[];
  align?: "start" | "end";
  className?: string;
}

/**
 * Menu dropdown with full keyboard navigation (↑/↓/Home/End/Escape/Enter).
 *
 * @example
 * <Dropdown trigger={({ref, toggle}) => <button ref={ref} onClick={toggle}>Menu</button>} items={[...]} />
 */
export function Dropdown({ trigger, items, align = "start", className }: DropdownProps) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLUListElement>(null);

  const toggle = useCallback(() => setOpen((o) => !o), []);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      const t = e.target as Node;
      if (menuRef.current?.contains(t)) return;
      if (triggerRef.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  // Reset active index + focus menu when opening
  useEffect(() => {
    if (open) {
      const firstEnabled = items.findIndex((i) => !i.disabled);
      setActive(firstEnabled >= 0 ? firstEnabled : 0);
      // Focus menu on next tick so keyboard events route correctly
      queueMicrotask(() => menuRef.current?.focus());
    }
  }, [open, items]);

  const moveActive = (dir: 1 | -1) => {
    setActive((curr) => {
      let next = curr;
      for (let i = 0; i < items.length; i++) {
        next = (next + dir + items.length) % items.length;
        if (!items[next]?.disabled) return next;
      }
      return curr;
    });
  };

  const onKeyDown = (e: KeyboardEvent<HTMLUListElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      moveActive(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      moveActive(-1);
    } else if (e.key === "Home") {
      e.preventDefault();
      setActive(items.findIndex((i) => !i.disabled));
    } else if (e.key === "End") {
      e.preventDefault();
      for (let i = items.length - 1; i >= 0; i--) {
        if (!items[i]?.disabled) {
          setActive(i);
          break;
        }
      }
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      const it = items[active];
      if (it && !it.disabled) {
        it.onSelect?.();
        setOpen(false);
        triggerRef.current?.focus();
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  };

  return (
    <div className="relative inline-block">
      {trigger({ open, toggle, ref: triggerRef })}
      {open && (
        <ul
          ref={menuRef}
          role="menu"
          onKeyDown={onKeyDown}
          tabIndex={-1}
          className={cn(
            "absolute z-40 mt-1 min-w-[10rem] overflow-hidden rounded-md border border-lattice-strong bg-paper shadow-lg font-sans text-sm",
            align === "end" ? "right-0" : "left-0",
            className
          )}
        >
          {items.map((it, i) => (
            <li key={it.id} role="none">
              <button
                role="menuitem"
                type="button"
                disabled={it.disabled}
                onMouseEnter={() => !it.disabled && setActive(i)}
                onClick={() => {
                  if (it.disabled) return;
                  it.onSelect?.();
                  setOpen(false);
                  triggerRef.current?.focus();
                }}
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-2 text-left outline-none",
                  it.disabled && "opacity-50 cursor-not-allowed",
                  !it.disabled && active === i && "bg-paper-fold",
                  it.danger ? "text-crane-deep" : "text-ink"
                )}
              >
                {it.icon && (
                  <span aria-hidden className="inline-flex h-4 w-4">
                    {it.icon}
                  </span>
                )}
                <span className="flex-1 truncate">{it.label}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
