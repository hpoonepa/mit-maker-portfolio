import { forwardRef, useId, type SelectHTMLAttributes, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "../utils/cn";

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  hint?: string;
  error?: string;
  options?: SelectOption[];
  placeholder?: string;
  containerClassName?: string;
  children?: ReactNode;
}

const BASE =
  "w-full appearance-none rounded-md bg-paper border border-lattice-strong pl-3 pr-9 py-2 " +
  "text-sm text-ink font-sans cursor-pointer " +
  "transition-colors duration-150 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane focus-visible:border-crane " +
  "disabled:opacity-50 disabled:cursor-not-allowed " +
  "aria-[invalid=true]:border-crane-deep aria-[invalid=true]:ring-1 aria-[invalid=true]:ring-crane-deep";

/**
 * Native `<select>` styled to match the Paper Crane palette. Pass `options` or `children`.
 *
 * @example
 * <Select label="Plan" options={[{value: "pro", label: "Pro"}]} />
 */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { id, label, hint, error, options, placeholder, children, className, containerClassName, ...rest },
  ref
) {
  const autoId = useId();
  const fieldId = id ?? `sel-${autoId}`;
  const hintId = hint ? `${fieldId}-hint` : undefined;
  const errorId = error ? `${fieldId}-err` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className={cn("flex flex-col gap-1.5", containerClassName)}>
      {label && (
        <label htmlFor={fieldId} className="text-xs font-medium text-ink-soft tracking-wide font-sans">
          {label}
        </label>
      )}
      <div className="relative">
        <select
          id={fieldId}
          ref={ref}
          aria-invalid={error ? "true" : "false"}
          aria-describedby={describedBy}
          className={cn(BASE, className)}
          {...rest}
        >
          {placeholder && (
            <option value="" disabled>
              {placeholder}
            </option>
          )}
          {options?.map((o) => (
            <option key={o.value} value={o.value} disabled={o.disabled}>
              {o.label}
            </option>
          ))}
          {children}
        </select>
        <ChevronDown
          className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-graphite-soft"
          aria-hidden
        />
      </div>
      {hint && !error && (
        <p id={hintId} className="text-xs text-graphite-soft font-sans">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="text-xs text-crane-deep font-sans" role="alert">
          {error}
        </p>
      )}
    </div>
  );
});
