import { forwardRef, useId, type TextareaHTMLAttributes } from "react";
import { cn } from "../utils/cn";

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  hint?: string;
  error?: string;
  containerClassName?: string;
}

const BASE =
  "w-full rounded-md bg-paper border border-lattice-strong px-3 py-2 " +
  "text-sm text-ink placeholder:text-graphite-soft font-sans " +
  "transition-colors duration-150 resize-y min-h-[88px] " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane focus-visible:border-crane " +
  "disabled:opacity-50 disabled:cursor-not-allowed " +
  "aria-[invalid=true]:border-crane-deep aria-[invalid=true]:ring-1 aria-[invalid=true]:ring-crane-deep";

/**
 * Multi-line text input with label, hint and error slots.
 *
 * @example
 * <Textarea label="Notes" rows={4} />
 */
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { id, label, hint, error, className, containerClassName, ...rest },
  ref
) {
  const autoId = useId();
  const fieldId = id ?? `ta-${autoId}`;
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
      <textarea
        id={fieldId}
        ref={ref}
        aria-invalid={error ? "true" : "false"}
        aria-describedby={describedBy}
        className={cn(BASE, className)}
        {...rest}
      />
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
