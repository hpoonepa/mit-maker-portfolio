import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "../utils/cn";

export interface SwitchProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "size"> {
  label?: ReactNode;
  description?: ReactNode;
  containerClassName?: string;
}

/**
 * On/off switch built on a native checkbox. Keyboard and screen reader compatible.
 *
 * @example
 * <Switch label="Notifications" defaultChecked />
 */
export const Switch = forwardRef<HTMLInputElement, SwitchProps>(function Switch(
  { id, label, description, className, containerClassName, ...rest },
  ref
) {
  const autoId = useId();
  const fieldId = id ?? `sw-${autoId}`;
  return (
    <label
      htmlFor={fieldId}
      className={cn(
        "flex items-start gap-3 cursor-pointer select-none font-sans",
        rest.disabled && "opacity-50 cursor-not-allowed",
        containerClassName
      )}
    >
      <span className="relative inline-flex h-5 w-9 shrink-0 items-center">
        <input
          id={fieldId}
          ref={ref}
          type="checkbox"
          role="switch"
          className={cn(
            "peer h-5 w-9 appearance-none rounded-full bg-paper-deep border border-lattice-strong",
            "checked:bg-crane checked:border-crane",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane focus-visible:ring-offset-1 focus-visible:ring-offset-paper",
            "transition-colors duration-150",
            "disabled:cursor-not-allowed",
            className
          )}
          {...rest}
        />
        <span
          className={cn(
            "pointer-events-none absolute left-0.5 top-1/2 -translate-y-1/2 h-4 w-4 rounded-full bg-paper shadow",
            "transition-transform duration-150",
            "peer-checked:translate-x-4"
          )}
        />
      </span>
      {(label || description) && (
        <span className="flex flex-col">
          {label && <span className="text-sm text-ink leading-tight">{label}</span>}
          {description && <span className="text-xs text-graphite-soft mt-0.5">{description}</span>}
        </span>
      )}
    </label>
  );
});
