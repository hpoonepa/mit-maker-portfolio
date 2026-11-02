import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import React, { type ReactNode } from "react";
import { ToastProvider } from "@/components/toasts/ToastProvider";
import { useToast } from "@/components/toasts/useToast";

/**
 * useToast: contract
 *
 *   - returns a stable `toast` fn that pushes a toast into provider state
 *   - `toast` accepts variants: success | error | info | warning
 *   - success/info default to 5s duration, error/warning default to 8s
 *   - max 3 toasts visible (4th push evicts the oldest)
 *   - duration override via explicit `duration` arg
 *   - dismiss removes a toast by id
 *
 * State is verified by reading the provider's `toasts` list via a second
 * hook, `useToastsInternal`, re-exported from ToastProvider for test use.
 */

function wrapper({ children }: { children: ReactNode }) {
  return React.createElement(ToastProvider, null, children);
}

describe("useToast", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("throws when called outside a ToastProvider", () => {
    const { result } = renderHook(() => {
      try {
        return useToast();
      } catch (err) {
        return err as Error;
      }
    });
    expect(result.current).toBeInstanceOf(Error);
  });

  it("pushes a toast and returns an id", () => {
    const { result } = renderHook(() => useToast(), { wrapper });

    let id = "";
    act(() => {
      id = result.current.toast({ title: "Saved", variant: "success" });
    });

    expect(typeof id).toBe("string");
    expect(id.length).toBeGreaterThan(0);
  });

  it("caps visible toasts at 3 (oldest evicted on overflow)", () => {
    const { result } = renderHook(() => useToast(), { wrapper });

    const ids: string[] = [];
    act(() => {
      ids.push(result.current.toast({ title: "1", variant: "info" }));
      ids.push(result.current.toast({ title: "2", variant: "info" }));
      ids.push(result.current.toast({ title: "3", variant: "info" }));
      ids.push(result.current.toast({ title: "4", variant: "info" }));
    });

    // All ids are unique
    expect(new Set(ids).size).toBe(4);
    // Visible count after overflow = 3 (verified via listing API)
    expect(result.current.getActive().length).toBe(3);
    // Oldest evicted
    expect(result.current.getActive().map((t) => t.title)).toEqual([
      "2",
      "3",
      "4",
    ]);
  });

  it("auto-dismisses success toasts after 5s", () => {
    const { result } = renderHook(() => useToast(), { wrapper });

    act(() => {
      result.current.toast({ title: "ok", variant: "success" });
    });
    expect(result.current.getActive()).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(result.current.getActive()).toHaveLength(0);
  });

  it("auto-dismisses error toasts after 8s", () => {
    const { result } = renderHook(() => useToast(), { wrapper });

    act(() => {
      result.current.toast({ title: "boom", variant: "error" });
    });
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(result.current.getActive()).toHaveLength(1);
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(result.current.getActive()).toHaveLength(0);
  });

  it("honors an explicit duration override", () => {
    const { result } = renderHook(() => useToast(), { wrapper });

    act(() => {
      result.current.toast({ title: "slow", variant: "info", duration: 10_000 });
    });
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(result.current.getActive()).toHaveLength(1);
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(result.current.getActive()).toHaveLength(0);
  });

  it("dismiss(id) removes a specific toast immediately", () => {
    const { result } = renderHook(() => useToast(), { wrapper });

    let id = "";
    act(() => {
      id = result.current.toast({ title: "x", variant: "info" });
    });
    act(() => {
      result.current.dismiss(id);
    });
    expect(result.current.getActive()).toHaveLength(0);
  });
});
