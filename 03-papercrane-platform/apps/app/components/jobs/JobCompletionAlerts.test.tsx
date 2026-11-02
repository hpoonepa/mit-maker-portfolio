import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { JobAlertToggle, JobCompletionAlerts } from "./JobCompletionAlerts";
const mocks = vi.hoisted(() => ({
  query: { data: { status: "running" } },
  toast: vi.fn(),
  notify: vi.fn(),
  permission: vi.fn(),
}));
vi.mock("@/lib/trpc/client", () => ({
  trpc: { jobs: { get: { useQuery: () => mocks.query } } },
}));
vi.mock("@/components/toasts/useToast", () => ({
  useToast: () => ({ toast: mocks.toast }),
}));
class FakeNotification {
  static permission = "granted";
  static requestPermission = mocks.permission;
  onclick: (() => void) | null = null;
  constructor(title: string, options: unknown) {
    mocks.notify(title, options);
  }
  close() {}
}
const page = (scope = "user:org", showToggle = true) => (
  <JobCompletionAlerts scope={scope}>
    {showToggle ? (
      <JobAlertToggle jobId="job1" toolName="RFdiffusion" />
    ) : (
      <p>Another page</p>
    )}
  </JobCompletionAlerts>
);
beforeEach(() => {
  sessionStorage.clear();
  vi.clearAllMocks();
  mocks.query.data = { status: "running" };
  FakeNotification.permission = "granted";
  vi.stubGlobal("Notification", FakeNotification);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("completion alerts", () => {
  it("continues watching after leaving the run and only sends once it finishes", async () => {
    const { rerender } = render(page());
    fireEvent.click(
      screen.getByRole("switch", { name: "Notify when finished" }),
    );
    await waitFor(() =>
      expect((screen.getByRole("switch") as HTMLInputElement).checked).toBe(
        true,
      ),
    );
    expect(mocks.notify).not.toHaveBeenCalled();
    rerender(page("user:org", false));
    mocks.query.data = { status: "succeeded" };
    rerender(page("user:org", false));
    await waitFor(() => expect(mocks.notify).toHaveBeenCalledOnce());
    expect(mocks.notify).toHaveBeenCalledWith(
      "Papercrane",
      expect.objectContaining({ body: "RFdiffusion finished" }),
    );
    rerender(page("user:org", false));
    expect(mocks.notify).toHaveBeenCalledOnce();
    expect(sessionStorage.getItem("papercrane:job-alerts:user:org")).toBe("[]");
  });
  it("does not turn on or claim success when permission is denied", async () => {
    FakeNotification.permission = "default";
    mocks.permission.mockResolvedValue("denied");
    render(page());
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "Allow notifications",
      ),
    );
    expect((screen.getByRole("switch") as HTMLInputElement).checked).toBe(
      false,
    );
    expect(mocks.notify).not.toHaveBeenCalled();
  });
  it("restores the alert on reload within the same account and tab", () => {
    sessionStorage.setItem(
      "papercrane:job-alerts:user:org",
      JSON.stringify([{ id: "job1", name: "RFdiffusion" }]),
    );
    render(page());
    expect((screen.getByRole("switch") as HTMLInputElement).checked).toBe(true);
  });
  it("never loads another account's subscriptions", () => {
    sessionStorage.setItem(
      "papercrane:job-alerts:other:org",
      JSON.stringify([{ id: "job1", name: "RFdiffusion" }]),
    );
    render(page());
    expect((screen.getByRole("switch") as HTMLInputElement).checked).toBe(
      false,
    );
  });
  it("stops watching when the switch is turned off", async () => {
    const { rerender } = render(page());
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() =>
      expect((screen.getByRole("switch") as HTMLInputElement).checked).toBe(
        true,
      ),
    );
    fireEvent.click(screen.getByRole("switch"));
    mocks.query.data = { status: "succeeded" };
    rerender(page());
    expect(mocks.notify).not.toHaveBeenCalled();
  });
});
