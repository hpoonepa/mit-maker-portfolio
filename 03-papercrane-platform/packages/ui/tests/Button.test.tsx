import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Button } from "../src/primitives/Button";

describe("Button", () => {
  it("renders children", () => {
    render(<Button>Click me</Button>);
    expect(screen.getByRole("button", { name: "Click me" })).toBeInTheDocument();
  });

  it("applies primary variant classes by default", () => {
    render(<Button>Primary</Button>);
    const btn = screen.getByRole("button");
    expect(btn.className).toMatch(/bg-crane/);
  });

  it("applies secondary variant classes", () => {
    render(<Button variant="secondary">S</Button>);
    expect(screen.getByRole("button").className).toMatch(/bg-paper-fold|border/);
  });

  it("applies ghost variant classes", () => {
    render(<Button variant="ghost">G</Button>);
    expect(screen.getByRole("button").className).toMatch(/bg-transparent/);
  });

  it("applies danger variant classes", () => {
    render(<Button variant="danger">D</Button>);
    expect(screen.getByRole("button").className).toMatch(/bg-crane-deep|text-paper/);
  });

  it("supports size prop", () => {
    const { rerender } = render(<Button size="sm">S</Button>);
    expect(screen.getByRole("button").className).toMatch(/text-xs|h-8/);
    rerender(<Button size="lg">L</Button>);
    expect(screen.getByRole("button").className).toMatch(/text-base|h-12/);
  });

  it("fires onClick handler", async () => {
    const handler = vi.fn();
    render(<Button onClick={handler}>Go</Button>);
    await userEvent.click(screen.getByRole("button"));
    expect(handler).toHaveBeenCalledOnce();
  });

  it("respects disabled prop", async () => {
    const handler = vi.fn();
    render(
      <Button onClick={handler} disabled>
        Off
      </Button>
    );
    const btn = screen.getByRole("button");
    expect(btn).toBeDisabled();
    await userEvent.click(btn);
    expect(handler).not.toHaveBeenCalled();
  });

  it("shows loading state and disables click", async () => {
    const handler = vi.fn();
    render(
      <Button onClick={handler} loading>
        Save
      </Button>
    );
    const btn = screen.getByRole("button");
    expect(btn).toHaveAttribute("aria-busy", "true");
    expect(btn).toBeDisabled();
    await userEvent.click(btn);
    expect(handler).not.toHaveBeenCalled();
  });

  it("merges custom className", () => {
    render(<Button className="custom-xyz">X</Button>);
    expect(screen.getByRole("button").className).toContain("custom-xyz");
  });

  it("forwards ref to the button element", () => {
    const ref = { current: null as HTMLButtonElement | null };
    render(<Button ref={ref}>R</Button>);
    expect(ref.current).toBeInstanceOf(HTMLButtonElement);
  });
});
