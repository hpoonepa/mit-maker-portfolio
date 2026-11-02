import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from "react";
import { Check } from "lucide-react";
import { cn } from "../utils/cn";

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: ReactNode;
  description?: ReactNode;
  error?: string;
  containerClassName?: string;
}

/**
 * Styled native checkbox with optional label and description.
 *
 * @example
 * <Checkbox label="Accept terms" defaultChecked />
 */
export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { id, label, description, error, className, containerClassName, ...rest },
  ref
) {
  const autoId = useId();
  const fieldId = id ?? `cb-${autoId}`;
  return (
    <label
      htmlFor={fieldId}
      className={cn(
        "flex items-start gap-2.5 cursor-pointer select-none font-sans",
        rest.disabled && "opacity-50 cursor-not-allowed",
        containerClassName
      )}
    >
      <span className="relative inline-flex h-4 w-4 shrink-0 items-center justify-center">
        <input
          id={fieldId}
          ref={ref}
          type="checkbox"
          aria-invalid={error ? "true" : undefined}
          className={cn(
            "peer h-4 w-4 appearance-none rounded border border-lattice-strong bg-paper",
            "checked:bg-crane checked:border-crane",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane focus-visible:ring-offset-1 focus-visible:ring-offset-paper",
            "disabled:cursor-not-allowed",
            className
          )}
          {...rest}
        />
        <Check
          className="pointer-events-none absolute h-3 w-3 text-paper opacity-0 peer-checked:opacity-100"
          aria-hidden
        />
      </span>
      {(label || description) && (
        <span className="flex flex-col">
          {label && <span className="text-sm text-ink leading-tight">{label}</span>}
          {description && <span className="text-xs text-graphite-soft mt-0.5">{description}</span>}
          {error && <span className="text-xs text-crane-deep mt-0.5">{error}</span>}
        </span>
      )}
    </label>
  );
});
