import { StrictMode } from "react";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { codecs, useFilters } from "./useFilters";

let lastSearch: string | undefined;
let params: URLSearchParams;
vi.mock("next/navigation", () => ({
  usePathname: () => "/app/projects",
  useSearchParams: () => {
    if (lastSearch !== window.location.search) {
      lastSearch = window.location.search;
      params = new URLSearchParams(lastSearch);
    }
    return params;
  },
}));

const schema = { search: codecs.string("q"), active: codecs.bool("active") };
type Filters = { search: string; active: boolean };

describe("workspace URL filters", () => {
  beforeEach(() =>
    window.history.replaceState(null, "", "/app/projects?keep=1"),
  );

  it("combines rapid changes and clears search without restoring stale values", () => {
    const { result } = renderHook(() => useFilters<Filters>(schema), {
      wrapper: StrictMode,
    });
    act(() => {
      result.current.setFilter("search", "ProteinMPNN");
      result.current.setFilter("active", true);
    });
    expect(result.current.filters).toEqual({
      search: "ProteinMPNN",
      active: true,
    });
    expect(new URLSearchParams(window.location.search).get("q")).toBe(
      "ProteinMPNN",
    );
    act(() => result.current.setFilter("search", ""));
    expect(result.current.filters).toEqual({ search: "", active: true });
    expect(window.location.search).toBe("?keep=1&active=1");
    act(() => result.current.reset());
    expect(result.current.isDefault).toBe(true);
    expect(window.location.search).toBe("?keep=1");
  });

  it("restores filters from external history navigation", () => {
    const { result, rerender } = renderHook(() => useFilters<Filters>(schema));
    act(() => result.current.applyAll({ search: "binder", active: true }));
    const forwardUrl = window.location.href;
    act(() => window.history.replaceState(null, "", "/app/projects?q=back"));
    rerender();
    expect(result.current.filters).toEqual({ search: "back", active: false });
    act(() => window.history.replaceState(null, "", forwardUrl));
    rerender();
    expect(result.current.filters).toEqual({ search: "binder", active: true });
  });
});
