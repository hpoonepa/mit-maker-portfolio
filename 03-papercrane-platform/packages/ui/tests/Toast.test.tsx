import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { ToastProvider, useToast } from "../src/feedback/Toast";

function Trigger({ duration }: { duration?: number }) {
  const { addToast } = useToast();
  return (
    <button
      onClick={() =>
        addToast({
          title: "Saved",
          description: "Your changes are saved",
          variant: "success",
          duration,
        })
      }
    >
      fire
    </button>
  );
}

describe("Toast", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("provider exposes addToast and renders a toast", async () => {
    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText("fire"));
    expect(screen.getByText("Saved")).toBeInTheDocument();
    expect(screen.getByText("Your changes are saved")).toBeInTheDocument();
  });

  it("auto-dismisses after duration", async () => {
    render(
      <ToastProvider>
        <Trigger duration={1000} />
      </ToastProvider>
    );
    fireEvent.click(screen.getByText("fire"));
    expect(screen.getByText("Saved")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(1100);
    });
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  });

  it("throws if used outside the provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Trigger />)).toThrow(/ToastProvider/);
    spy.mockRestore();
  });
});
