import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from "react";

/**
 * Persist a React state value to `localStorage`. SSR-safe: falls back to the
 * initial value when `window` is unavailable.
 *
 * @example
 * const [theme, setTheme] = useLocalStorage<"light" | "dark">("theme", "light");
 */
export function useLocalStorage<T>(
  key: string,
  initialValue: T
): [T, Dispatch<SetStateAction<T>>, () => void] {
  const read = (): T => {
    if (typeof window === "undefined") return initialValue;
    try {
      const raw = window.localStorage.getItem(key);
      return raw !== null ? (JSON.parse(raw) as T) : initialValue;
    } catch {
      return initialValue;
    }
  };

  const [value, setValue] = useState<T>(read);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // swallow quota / privacy errors silently
    }
  }, [key, value]);

  // Listen to cross-tab updates
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onStorage = (e: StorageEvent) => {
      if (e.key !== key) return;
      try {
        setValue(e.newValue !== null ? (JSON.parse(e.newValue) as T) : initialValue);
      } catch {
        // ignore malformed values
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [key, initialValue]);

  const remove = useCallback(() => {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(key);
    }
    setValue(initialValue);
  }, [key, initialValue]);

  return [value, setValue, remove];
}
