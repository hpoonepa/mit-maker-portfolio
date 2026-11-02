import { forwardRef, useState, type HTMLAttributes } from "react";
import { cn } from "../utils/cn";

export type AvatarSize = "xs" | "sm" | "md" | "lg";

export interface AvatarProps extends HTMLAttributes<HTMLSpanElement> {
  name: string;
  src?: string | null;
  size?: AvatarSize;
  alt?: string;
}

const SIZE: Record<AvatarSize, string> = {
  xs: "h-6 w-6 text-[10px]",
  sm: "h-8 w-8 text-xs",
  md: "h-10 w-10 text-sm",
  lg: "h-14 w-14 text-base",
};

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}

/**
 * Avatar with image support and automatic initials fallback.
 *
 * @example
 * <Avatar name="Harsha P" src={user.avatarUrl} size="md" />
 */
export const Avatar = forwardRef<HTMLSpanElement, AvatarProps>(function Avatar(
  { name, src, size = "md", alt, className, ...rest },
  ref
) {
  const [failed, setFailed] = useState(false);
  const showImg = !!src && !failed;

  return (
    <span
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center overflow-hidden rounded-full bg-paper-deep text-ink font-sans font-semibold select-none",
        SIZE[size],
        className
      )}
      {...rest}
    >
      {showImg ? (
        <img
          src={src!}
          alt={alt ?? name}
          className="h-full w-full object-cover"
          onError={() => setFailed(true)}
        />
      ) : (
        <span aria-hidden>{initials(name) || "?"}</span>
      )}
    </span>
  );
});
