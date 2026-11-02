import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "../utils/cn";

export interface RadioProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: ReactNode;
  description?: ReactNode;
  containerClassName?: string;
}

/**
 * Styled native radio input. Group by shared `name` prop.
 *
 * @example
 * <Radio name="plan" value="pro" label="Pro" />
 */
export const Radio = forwardRef<HTMLInputElement, RadioProps>(function Radio(
  { id, label, description, className, containerClassName, ...rest },
  ref
) {
  const autoId = useId();
  const fieldId = id ?? `rd-${autoId}`;
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
          type="radio"
          className={cn(
            "peer h-4 w-4 appearance-none rounded-full border border-lattice-strong bg-paper",
            "checked:border-crane",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane focus-visible:ring-offset-1 focus-visible:ring-offset-paper",
            "disabled:cursor-not-allowed",
            className
          )}
          {...rest}
        />
        <span className="pointer-events-none absolute h-2 w-2 rounded-full bg-crane opacity-0 peer-checked:opacity-100" />
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
