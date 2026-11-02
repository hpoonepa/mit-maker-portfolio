import { describe, it, expect, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { Dialog } from "../src/primitives/Dialog";

function Harness({ onOpenChange }: { onOpenChange?: (o: boolean) => void }) {
  const [open, setOpen] = useState(true);
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        onOpenChange?.(o);
      }}
      title="My Dialog"
    >
      <button>inside-1</button>
      <input aria-label="text" />
      <button>inside-2</button>
    </Dialog>
  );
}

describe("Dialog", () => {
  it("renders when open", () => {
    render(<Harness />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("My Dialog")).toBeInTheDocument();
  });

  it("does not render when closed", () => {
    render(
      <Dialog open={false} onOpenChange={() => {}} title="Closed">
        <p>hidden</p>
      </Dialog>
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("calls onOpenChange(false) on Escape", async () => {
    const onOpenChange = vi.fn();
    render(<Harness onOpenChange={onOpenChange} />);
    await userEvent.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("calls onOpenChange(false) when close button clicked", async () => {
    const onOpenChange = vi.fn();
    render(<Harness onOpenChange={onOpenChange} />);
    await userEvent.click(screen.getByLabelText(/close/i));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("traps focus within the dialog", async () => {
    render(<Harness />);
    // Focus the last focusable, then Tab should wrap to first
    const last = screen.getByRole("button", { name: "inside-2" });
    const first = screen.getByLabelText(/close/i);
    act(() => last.focus());
    expect(document.activeElement).toBe(last);
    await userEvent.tab();
    expect(document.activeElement).toBe(first);
  });

  it("shift-tab from first focusable wraps to last", async () => {
    render(<Harness />);
    const last = screen.getByRole("button", { name: "inside-2" });
    const closeBtn = screen.getByLabelText(/close/i);
    act(() => closeBtn.focus());
    await userEvent.tab({ shift: true });
    expect(document.activeElement).toBe(last);
  });
});
