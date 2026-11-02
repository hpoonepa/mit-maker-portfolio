import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "../utils/cn";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: string;
  error?: string;
  leftAddon?: ReactNode;
  rightAddon?: ReactNode;
  containerClassName?: string;
}

const INPUT_BASE =
  "w-full rounded-md bg-paper border border-lattice-strong px-3 py-2 " +
  "text-sm text-ink placeholder:text-graphite-soft font-sans " +
  "transition-[border-color,box-shadow,background-color] duration-150 ease-out " +
  // Editorial focus: 1px crane border + soft crane-glow halo (no neon ring)
  "hover:border-ink/30 " +
  "focus:outline-none focus:border-crane focus:shadow-[0_0_0_3px_rgba(193,39,45,0.14)] " +
  "focus-visible:outline-none focus-visible:border-crane focus-visible:shadow-[0_0_0_3px_rgba(193,39,45,0.14)] " +
  "disabled:opacity-50 disabled:cursor-not-allowed disabled:bg-paper-fold " +
  "aria-[invalid=true]:border-crane-deep aria-[invalid=true]:shadow-[0_0_0_3px_rgba(150,28,33,0.18)]";

/**
 * Text input with optional label, hint, and error slot. aria-invalid is wired
 * automatically when `error` is present.
 *
 * @example
 * <Input label="Email" type="email" error={errors.email} />
 */
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  {
    id,
    label,
    hint,
    error,
    leftAddon,
    rightAddon,
    className,
    containerClassName,
    type = "text",
    ...rest
  },
  ref
) {
  const autoId = useId();
  const inputId = id ?? `inp-${autoId}`;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const errorId = error ? `${inputId}-err` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className={cn("flex flex-col gap-1.5", containerClassName)}>
      {label && (
        <label
          htmlFor={inputId}
          className="text-xs font-medium text-ink-soft tracking-wide font-sans"
        >
          {label}
        </label>
      )}
      <div className={cn("relative flex items-center", leftAddon || rightAddon ? "gap-2" : "")}>
        {leftAddon && (
          <span className="absolute left-3 text-graphite-soft pointer-events-none" aria-hidden>
            {leftAddon}
          </span>
        )}
        <input
          id={inputId}
          ref={ref}
          type={type}
          aria-invalid={error ? "true" : undefined}
          aria-errormessage={errorId}
          aria-describedby={describedBy}
          className={cn(
            INPUT_BASE,
            leftAddon && "pl-9",
            rightAddon && "pr-9",
            className
          )}
          {...rest}
        />
        {rightAddon && (
          <span className="absolute right-3 text-graphite-soft pointer-events-none" aria-hidden>
            {rightAddon}
          </span>
        )}
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
