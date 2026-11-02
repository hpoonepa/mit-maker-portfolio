/** Shared with the public site's folded-crane mark. */
export function CraneMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 48 40"
      className={className}
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <path d="m20 23 14-20-3 16Z" fill="currentColor" opacity=".52" />
      <path d="M20 23 11 3l20 16Z" fill="currentColor" />
      <path d="M3 18 20 23 18 31Z" fill="currentColor" opacity=".72" />
      <path d="m20 23 11-4-3 14-10-2Z" fill="currentColor" opacity=".9" />
      <path d="m28 33 7-19 5-2 6 6-7-2-2 2-5 17Z" fill="currentColor" />
      <path
        d="m20 23 8 10M20 23 31 19"
        stroke="#07100d"
        strokeWidth=".8"
        opacity=".65"
      />
    </svg>
  );
}
