import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MolecularDynamicsWaitlist } from "./MolecularDynamicsWaitlist";

const mocks = vi.hoisted(() => ({
  status: { data: { joined: false }, isLoading: false },
  join: { data: undefined as { joined: boolean } | undefined, isPending: false, error: null as Error | null, mutate: vi.fn() },
  invalidate: vi.fn(),
}));
vi.mock("@/lib/trpc/client", () => ({ trpc: {
  feedback: {
    molecularDynamicsWaitlist: { useQuery: () => mocks.status },
    joinMolecularDynamicsWaitlist: { useMutation: () => mocks.join },
  },
  useUtils: () => ({ feedback: { molecularDynamicsWaitlist: { invalidate: mocks.invalidate } } }),
} }));
beforeEach(() => {
  mocks.status.data = { joined: false };
  mocks.status.isLoading = false;
  mocks.join.data = undefined;
  mocks.join.error = null;
  mocks.join.isPending = false;
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("molecular dynamics waitlist", () => {
  it("only confirms a place after the server saves it", () => {
    const { rerender } = render(<MolecularDynamicsWaitlist />);
    fireEvent.click(screen.getByRole("button", { name: "Join waitlist" }));
    expect(mocks.join.mutate).toHaveBeenCalledOnce();
    expect(screen.queryByRole("status")).toBeNull();
    mocks.join.data = { joined: true };
    rerender(<MolecularDynamicsWaitlist />);
    expect(screen.getByRole("status").textContent).toContain("You’re on the waitlist");
    expect(screen.queryByRole("button")).toBeNull();
  });
  it("restores saved membership after a page load", () => {
    mocks.status.data = { joined: true };
    render(<MolecularDynamicsWaitlist />);
    expect(screen.getByRole("status").textContent).toContain("You’re on the waitlist");
    expect(screen.queryByRole("button", { name: "Join waitlist" })).toBeNull();
  });
  it("keeps failures retryable and does not claim success", () => {
    mocks.join.error = new Error("Save failed");
    render(<MolecularDynamicsWaitlist />);
    expect(screen.getByRole("alert").textContent).toContain("Please try again");
    expect(screen.getByRole("button", { name: "Join waitlist" }).hasAttribute("disabled")).toBe(false);
    expect(screen.queryByRole("status")).toBeNull();
  });
});
