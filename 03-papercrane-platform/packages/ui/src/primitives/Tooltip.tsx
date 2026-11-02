import {
  cloneElement,
  isValidElement,
  useId,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import { cn } from "../utils/cn";

export interface TooltipProps {
  content: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  children: ReactElement<Record<string, unknown>>;
  className?: string;
  /** Show/hide delay in ms. */
  delay?: number;
}

const SIDE: Record<NonNullable<TooltipProps["side"]>, string> = {
  top: "bottom-full left-1/2 -translate-x-1/2 mb-2",
  right: "left-full top-1/2 -translate-y-1/2 ml-2",
  bottom: "top-full left-1/2 -translate-x-1/2 mt-2",
  left: "right-full top-1/2 -translate-y-1/2 mr-2",
};

/**
 * Hover + focus-triggered tooltip. Wraps a single interactive child.
 *
 * @example
 * <Tooltip content="Copy link"><button>Copy</button></Tooltip>
 */
export function Tooltip({ content, side = "top", children, className, delay = 100 }: TooltipProps) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  let timer: ReturnType<typeof setTimeout> | null = null;

  const show = () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => setVisible(true), delay);
  };
  const hide = () => {
    if (timer) clearTimeout(timer);
    setVisible(false);
  };

  if (!isValidElement(children)) return <>{children}</>;

  const cloned = cloneElement(children, {
    "aria-describedby": visible ? id : undefined,
    onMouseEnter: show,
    onMouseLeave: hide,
    onFocus: show,
    onBlur: hide,
  });

  return (
    <span className="relative inline-flex">
      {cloned}
      {visible && (
        <span
          role="tooltip"
          id={id}
          className={cn(
            "pointer-events-none absolute z-50 whitespace-nowrap rounded-md bg-ink px-2 py-1 text-xs text-paper shadow-lg font-sans",
            "animate-fade-in",
            SIDE[side],
            className
          )}
        >
          {content}
        </span>
      )}
    </span>
  );
}
