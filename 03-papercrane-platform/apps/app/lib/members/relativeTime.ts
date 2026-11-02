/**
 * Tiny "X minutes ago" / "in X days" formatter.
 *
 * We deliberately avoid pulling in `date-fns` or `Intl.RelativeTimeFormat`
 * here: they're either heavy or have inconsistent rounding across browsers.
 * The members table only needs coarse buckets (minutes / hours / days /
 * weeks / months / years) and the units are stable across locales for the
 * en-US-leaning copy we ship today.
 */

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;
const MONTH = 30 * DAY;
const YEAR = 365 * DAY;

export function formatRelative(input: string | Date | null | undefined): string {
  if (input == null) return "N/A";
  const date = typeof input === "string" ? new Date(input) : input;
  if (Number.isNaN(date.getTime())) return "N/A";

  const delta = date.getTime() - Date.now();
  const abs = Math.abs(delta);
  const past = delta < 0;

  if (abs < 30_000) return past ? "just now" : "in a moment";
  if (abs < HOUR) {
    const m = Math.round(abs / MIN);
    return past ? `${m}m ago` : `in ${m}m`;
  }
  if (abs < DAY) {
    const h = Math.round(abs / HOUR);
    return past ? `${h}h ago` : `in ${h}h`;
  }
  if (abs < WEEK) {
    const d = Math.round(abs / DAY);
    return past ? `${d}d ago` : `in ${d}d`;
  }
  if (abs < MONTH) {
    const w = Math.round(abs / WEEK);
    return past ? `${w}w ago` : `in ${w}w`;
  }
  if (abs < YEAR) {
    const mo = Math.round(abs / MONTH);
    return past ? `${mo}mo ago` : `in ${mo}mo`;
  }
  const y = Math.round(abs / YEAR);
  return past ? `${y}y ago` : `in ${y}y`;
}

/**
 * Variant that returns a longer, prose-friendly string used for tooltips
 * where the compact form is too terse ("3 weeks ago" instead of "3w ago").
 */
export function formatRelativeLong(input: string | Date | null | undefined): string {
  if (input == null) return "N/A";
  const date = typeof input === "string" ? new Date(input) : input;
  if (Number.isNaN(date.getTime())) return "N/A";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
