import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const invalidateGet = vi.fn();
const invalidateList = vi.fn();
const mutate = vi.fn();

vi.mock("@/lib/trpc/client", () => ({
  trpc: {
    useUtils: () => ({
      projects: {
        get: { invalidate: invalidateGet },
        list: { invalidate: invalidateList },
      },
    }),
    projects: {
      share: {
        useMutation: (options: {
          onSuccess: (result: { isPublic: boolean; publicId: string }) => void;
        }) => ({
          mutate: (input: { id: string; isPublic: boolean }) => {
            mutate(input);
            options.onSuccess({
              isPublic: input.isPublic,
              publicId: "prj_1234567890abcdefghijklmn",
            });
          },
          isPending: false,
          error: null,
        }),
      },
    },
  },
}));

import { ProjectShareToggle } from "./ProjectShareToggle";

describe("ProjectShareToggle", () => {
  afterEach(cleanup);

  beforeEach(() => {
    mutate.mockClear();
    invalidateGet.mockClear();
    invalidateList.mockClear();
  });

  it("creates a public link and reveals its URL", () => {
    render(<ProjectShareToggle projectId="project-1" />);

    expect(screen.getByText(/only workspace members/i)).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: /create public link/i }),
    );

    expect(mutate).toHaveBeenCalledWith({ id: "project-1", isPublic: true });
    expect(screen.getByText("Public link active")).toBeTruthy();
    expect(
      screen.getByText("papercrane.bio/p/prj_1234567890abcdefghijklmn"),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: /disable link/i })).toBeTruthy();
  });

  it("copies the complete public URL", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(
      <ProjectShareToggle
        projectId="project-1"
        isPublic
        publicId="prj_1234567890abcdefghijklmn"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /copy public url/i }));

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(
        "https://papercrane.bio/p/prj_1234567890abcdefghijklmn",
      );
    });
    expect(screen.getByText("Copied")).toBeTruthy();
  });
});
