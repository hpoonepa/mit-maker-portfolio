import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";
import { Toast } from "@/components/toasts/Toast";

/**
 * Toast: single-item rendering + dismissal contract.
 *
 * The Toast is a presentational component: it receives a descriptor and
 * an `onDismiss(id)` callback. Timer management is still owned here so
 * hover-to-pause can be asserted end-to-end.
 */

describe("Toast", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("renders title, description, and the variant icon role", () => {
    render(
      <Toast
        id="t1"
        title="Job complete"
        description="5 designs ready"
        variant="success"
        duration={5000}
        onDismiss={() => {}}
      />,
    );

    expect(screen.getByText("Job complete")).toBeTruthy();
    expect(screen.getByText("5 designs ready")).toBeTruthy();
    // Variant is exposed as data attribute for styling + tests.
    const root = screen.getByRole("status");
    expect(root.getAttribute("data-variant")).toBe("success");
  });

  it("calls onDismiss when the close button is clicked", () => {
    const onDismiss = vi.fn();
    render(
      <Toast
        id="t1"
        title="x"
        variant="info"
        duration={5000}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(onDismiss).toHaveBeenCalledWith("t1");
  });

  it("auto-dismisses after duration elapses", () => {
    const onDismiss = vi.fn();
    render(
      <Toast
        id="t1"
        title="x"
        variant="info"
        duration={5000}
        onDismiss={onDismiss}
      />,
    );
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(onDismiss).toHaveBeenCalledWith("t1");
  });

  it("pauses the auto-dismiss timer while hovered", () => {
    const onDismiss = vi.fn();
    render(
      <Toast
        id="t1"
        title="x"
        variant="info"
        duration={5000}
        onDismiss={onDismiss}
      />,
    );
    const root = screen.getByRole("status");
    act(() => {
      vi.advanceTimersByTime(2000);
      fireEvent.mouseEnter(root);
      vi.advanceTimersByTime(10_000);
    });
    expect(onDismiss).not.toHaveBeenCalled();
    // Resume on leave: remaining time is 3s.
    act(() => {
      fireEvent.mouseLeave(root);
      vi.advanceTimersByTime(3000);
    });
    expect(onDismiss).toHaveBeenCalledWith("t1");
  });
});
