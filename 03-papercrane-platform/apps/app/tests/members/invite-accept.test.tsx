/**
 * Component test for the invite-accept client flow.
 *
 * Strategy: we can't execute the real RSC page inside vitest, but we CAN
 * render `AcceptInviteClient` directly and assert that:
 *   1. the signed-in email is displayed
 *   2. clicking "Accept invite" calls the `members.acceptInvite` mutation
 *      with the token from props
 *   3. success -> "redirecting" banner appears
 *   4. failure -> user-readable error rendered in an alert region
 *
 * The tRPC client is mocked at module scope so we don't have to stand up a
 * QueryClientProvider or a fake HTTP server.
 */
import React from "react";
import { afterEach, describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  act,
  cleanup,
} from "@testing-library/react";

// React isn't auto-imported under vitest's default JSX transform, so bind
// it to globalThis for the classic-runtime fallback used here.
(globalThis as unknown as { React: typeof React }).React = React;

// `cleanup` isn't auto-registered under vitest's globals-less config.
afterEach(() => {
  cleanup();
});

// ─── Mocks ───────────────────────────────────────────────────────────────────

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

type MutationOptions<TData> = {
  onSuccess?: (data: TData) => void;
  onError?: (err: { message: string }) => void;
};

interface MutationHandle {
  mutate: (input: unknown) => void;
  isPending: boolean;
}

const mockAcceptInvite = vi.fn();

vi.mock("@/lib/trpc/client", () => ({
  trpc: {
    members: {
      acceptInvite: {
        useMutation: (opts?: MutationOptions<{ orgId: string; role: string }>) => {
          const handle: MutationHandle = {
            isPending: false,
            mutate: (input: unknown) => {
              // Delegate to the spy so tests can assert the call shape AND
              // control the async resolution path.
              mockAcceptInvite(input, opts);
            },
          };
          return handle;
        },
      },
    },
  },
}));

// Component has to be imported AFTER the mocks register.
import { AcceptInviteClient } from "@/components/members/AcceptInviteClient";

beforeEach(() => {
  pushMock.mockReset();
  mockAcceptInvite.mockReset();
  vi.useFakeTimers();
});

describe("<AcceptInviteClient />", () => {
  it("renders the caller's email so they can confirm the right account", () => {
    render(<AcceptInviteClient token="tok_123456789abcdef" userEmail="ada@lab.edu" />);
    expect(screen.getByText("ada@lab.edu")).toBeDefined();
    expect(
      screen.getByRole("button", { name: /accept invite/i }),
    ).toBeDefined();
  });

  it("invokes acceptInvite.mutate with the provided token when clicked", () => {
    render(<AcceptInviteClient token="tok_abcdef01234567" userEmail="ada@lab.edu" />);
    fireEvent.click(screen.getByRole("button", { name: /accept invite/i }));
    expect(mockAcceptInvite).toHaveBeenCalledTimes(1);
    const [input] = mockAcceptInvite.mock.calls[0]!;
    expect(input).toEqual({ token: "tok_abcdef01234567" });
  });

  it("on success shows the 'redirecting' banner and navigates to /home", () => {
    render(<AcceptInviteClient token="tok_abcdef01234567" userEmail="ada@lab.edu" />);
    fireEvent.click(screen.getByRole("button", { name: /accept invite/i }));

    const [, opts] = mockAcceptInvite.mock.calls[0]!;
    act(() => {
      opts?.onSuccess?.({ orgId: "org-uuid", role: "member" });
    });

    expect(
      screen.getByRole("status").textContent,
    ).toMatch(/redirecting/i);

    // Navigation is delayed by 500ms to let the banner render.
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(pushMock).toHaveBeenCalledWith("/home");
  });

  it("on failure renders an alert with the server-provided message", () => {
    render(<AcceptInviteClient token="tok_abcdef01234567" userEmail="ada@lab.edu" />);
    fireEvent.click(screen.getByRole("button", { name: /accept invite/i }));

    const [, opts] = mockAcceptInvite.mock.calls[0]!;
    act(() => {
      opts?.onError?.({ message: "invite has expired" });
    });

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toMatch(/expired/i);
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("offers a sign-out escape hatch when the wrong account is signed in", () => {
    render(<AcceptInviteClient token="tok_abcdef01234567" userEmail="ada@lab.edu" />);
    const link = screen.getByRole("link", { name: /sign out/i }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/logout");
  });
});
