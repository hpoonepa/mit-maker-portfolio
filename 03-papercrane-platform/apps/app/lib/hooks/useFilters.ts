"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";

/**
 * Generic URL-state-synced filter hook.
 *
 * - Filter state lives in `?key=value` query params and reacts to
 *   browser back/forward.
 * - Each field is encoded by a small adapter (string, number, range,
 *   list, boolean). Empty / default values are dropped from the URL so
 *   shared links stay short.
 * - Search input is debounced separately to avoid spamming history.
 */

export type FilterCodec<T> = {
  /** Read from URLSearchParams. Returns `undefined` to mean "use default". */
  parse: (params: URLSearchParams) => T | undefined;
  /** Write to a draft URLSearchParams. Should remove the key when empty. */
  serialize: (params: URLSearchParams, value: T) => void;
  /** Default value when the URL is empty. */
  default: T;
};

export const codecs = {
  string(key: string): FilterCodec<string> {
    return {
      default: "",
      parse: (p) => p.get(key) ?? undefined,
      serialize: (p, v) => {
        if (v && v.length > 0) p.set(key, v);
        else p.delete(key);
      },
    };
  },
  list(key: string): FilterCodec<string[]> {
    return {
      default: [],
      parse: (p) => {
        const raw = p.get(key);
        if (raw == null) return undefined;
        return raw.split(",").filter(Boolean);
      },
      serialize: (p, v) => {
        if (v && v.length > 0) p.set(key, v.join(","));
        else p.delete(key);
      },
    };
  },
  bool(key: string): FilterCodec<boolean> {
    return {
      default: false,
      parse: (p) => {
        const raw = p.get(key);
        if (raw == null) return undefined;
        return raw === "1" || raw === "true";
      },
      serialize: (p, v) => {
        if (v) p.set(key, "1");
        else p.delete(key);
      },
    };
  },
  range(
    keyMin: string,
    keyMax: string,
    bounds: { min: number; max: number },
  ): FilterCodec<{ min: number; max: number }> {
    return {
      default: { ...bounds },
      parse: (p) => {
        const a = p.get(keyMin);
        const b = p.get(keyMax);
        if (a == null && b == null) return undefined;
        const min = a != null ? Number(a) : bounds.min;
        const max = b != null ? Number(b) : bounds.max;
        if (Number.isNaN(min) || Number.isNaN(max)) return undefined;
        return { min, max };
      },
      serialize: (p, v) => {
        if (v.min !== bounds.min) p.set(keyMin, String(v.min));
        else p.delete(keyMin);
        if (v.max !== bounds.max) p.set(keyMax, String(v.max));
        else p.delete(keyMax);
      },
    };
  },
  dateRange(key: string): FilterCodec<DateRange> {
    return {
      default: { preset: "all", from: null, to: null },
      parse: (p) => {
        const preset = p.get(key) as DatePreset | null;
        if (!preset) return undefined;
        if (preset === "custom") {
          const from = p.get(`${key}_from`);
          const to = p.get(`${key}_to`);
          return { preset, from: from ?? null, to: to ?? null };
        }
        return { preset, from: null, to: null };
      },
      serialize: (p, v) => {
        if (!v.preset || v.preset === "all") {
          p.delete(key);
          p.delete(`${key}_from`);
          p.delete(`${key}_to`);
          return;
        }
        p.set(key, v.preset);
        if (v.preset === "custom") {
          if (v.from) p.set(`${key}_from`, v.from);
          else p.delete(`${key}_from`);
          if (v.to) p.set(`${key}_to`, v.to);
          else p.delete(`${key}_to`);
        } else {
          p.delete(`${key}_from`);
          p.delete(`${key}_to`);
        }
      },
    };
  },
};

export type DatePreset = "all" | "24h" | "7d" | "30d" | "custom";
export interface DateRange {
  preset: DatePreset;
  from: string | null;
  to: string | null;
}

// Internal schema type. Values are erased to `any` to avoid invariance
// problems when callers declare a state interface with a string index
// signature (e.g. `extends Record<string, unknown>`); we trust the
// matching is correct at the public hook boundary.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Schema<T> = { [K in keyof T]: FilterCodec<any> };

/** Parse search params into a record using a codec map. */
function readState<T>(params: URLSearchParams, schema: Schema<T>): T {
  const out = {} as T;
  for (const k of Object.keys(schema) as (keyof T)[]) {
    const codec = schema[k];
    const parsed = codec.parse(params);
    out[k] = (parsed === undefined ? codec.default : parsed) as T[typeof k];
  }
  return out;
}

/** Write state to a fresh URLSearchParams. */
function writeState<T>(
  state: T,
  schema: Schema<T>,
  base: URLSearchParams,
): URLSearchParams {
  const next = new URLSearchParams(base.toString());
  for (const k of Object.keys(schema) as (keyof T)[]) {
    schema[k].serialize(next, state[k]);
  }
  return next;
}

export interface UseFiltersResult<T> {
  filters: T;
  setFilter: <K extends keyof T>(key: K, value: T[K]) => void;
  setMany: (patch: Partial<T>) => void;
  reset: () => void;
  /** Apply a complete state object (e.g. from a saved view). */
  applyAll: (next: T) => void;
  isDefault: boolean;
}

/**
 * Hook that binds a filter state object to URL search params.
 *
 * @param schema - codec map describing each field
 * @param options.replace - use replaceState instead of pushState (default: false → push so back/fwd works)
 */
export function useFilters<T>(
  schema: Schema<T>,
  options: { replace?: boolean } = {},
): UseFiltersResult<T> {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Initial state from URL.
  const [state, setState] = useState<T>(() =>
    readState<T>(new URLSearchParams(searchParams?.toString() ?? ""), schema),
  );

  const stateRef = useRef(state);

  // Re-sync when URL changes externally (back/forward, programmatic nav).
  const lastWriteRef = useRef<string>("");
  useEffect(() => {
    const current = searchParams?.toString() ?? "";
    if (current === lastWriteRef.current) return;
    lastWriteRef.current = current;
    const next = readState<T>(new URLSearchParams(current), schema);
    stateRef.current = next;
    setState(next);
    // schema is stable per page; safe to omit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const push = useCallback(
    (next: T) => {
      const written = writeState<T>(
        next,
        schema,
        new URLSearchParams(window.location.search),
      );
      const qs = written.toString();
      lastWriteRef.current = qs;
      const url = qs ? `${pathname}?${qs}` : pathname;
      // Next.js syncs native history updates with useSearchParams. Filters
      // only affect client data, so avoid a server navigation and remount.
      if (options.replace) window.history.replaceState(null, "", url);
      else window.history.pushState(null, "", url);
    },
    [pathname, options.replace, schema],
  );

  const setFilter = useCallback(
    <K extends keyof T>(key: K, value: T[K]) => {
      const next = { ...stateRef.current, [key]: value };
      stateRef.current = next;
      setState(next);
      push(next);
    },
    [push],
  );

  const setMany = useCallback(
    (patch: Partial<T>) => {
      const next = { ...stateRef.current, ...patch } as T;
      stateRef.current = next;
      setState(next);
      push(next);
    },
    [push],
  );

  const reset = useCallback(() => {
    const fresh = {} as T;
    for (const k of Object.keys(schema) as (keyof T)[]) {
      fresh[k] = schema[k].default;
    }
    stateRef.current = fresh;
    setState(fresh);
    push(fresh);
  }, [schema, push]);

  const applyAll = useCallback(
    (next: T) => {
      stateRef.current = next;
      setState(next);
      push(next);
    },
    [push],
  );

  const isDefault = useMemo(() => {
    for (const k of Object.keys(schema) as (keyof T)[]) {
      const a = state[k];
      const b = schema[k].default;
      if (JSON.stringify(a) !== JSON.stringify(b)) return false;
    }
    return true;
  }, [state, schema]);

  return { filters: state, setFilter, setMany, reset, applyAll, isDefault };
}

/**
 * Debounce helper for search inputs. Local state updates immediately
 * (so the input feels snappy) and the debounced value is what should
 * drive the URL / query.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
}
