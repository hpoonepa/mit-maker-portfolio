import { describe, it, expect, vi } from "vitest";
import {
  residueIdFromMolstarEvent,
  buildHotspotHighlights,
  deriveCameraFocusSelection,
  shouldAnimateCamera,
  nextFocusResidue,
  clampSelectionToggle,
} from "./residueSelection";

/**
 * Unit tests for the 3D hotspot picker helpers.
 *
 * These helpers are kept side-effect free so we can test them under jsdom
 * without touching Mol* at all. The companion React component wires these
 * into the running plugin.
 */

describe("residueIdFromMolstarEvent", () => {
  it("extracts chain + residue from a structure-element loci payload", () => {
    const fakeLoci = {
      kind: "element-loci",
      structure: {},
      elements: [
        {
          unit: {
            model: {
              atomicHierarchy: {
                residues: {
                  auth_seq_id: { value: (_: number) => 104 },
                },
                chains: {
                  auth_asym_id: { value: (_: number) => "A" },
                },
                residueAtomSegments: {
                  index: { [Symbol.iterator]: () => ({ next: () => ({ done: true }) }) },
                },
              },
            },
            residueIndex: { value: (_: number) => 12 },
            chainIndex: { value: (_: number) => 0 },
          },
          indices: { start: 0, end: 1 },
        },
      ],
    };

    const id = residueIdFromMolstarEvent({ current: { loci: fakeLoci } });
    expect(id).toEqual({ chain: "A", resi: 104 });
  });

  it("returns null when loci is empty", () => {
    expect(
      residueIdFromMolstarEvent({ current: { loci: { kind: "empty-loci" } } }),
    ).toBeNull();
  });

  it("returns null for unknown event shapes", () => {
    expect(residueIdFromMolstarEvent(undefined)).toBeNull();
    expect(residueIdFromMolstarEvent({})).toBeNull();
    expect(residueIdFromMolstarEvent({ current: null })).toBeNull();
  });
});

describe("buildHotspotHighlights", () => {
  it("maps a selection set to DesignHighlight[] scoped to the target chain", () => {
    const selected = new Set([10, 42, 7]);
    const hl = buildHotspotHighlights(selected, "A");
    expect(hl).toHaveLength(3);
    expect(hl.every((h) => h.chainId === "A")).toBe(true);
    expect(hl.map((h) => h.resi).sort((a, b) => a - b)).toEqual([7, 10, 42]);
    expect(hl.every((h) => h.style === "sphere")).toBe(true);
  });

  it("handles an empty selection", () => {
    expect(buildHotspotHighlights(new Set(), "A")).toEqual([]);
  });
});

describe("deriveCameraFocusSelection", () => {
  it("returns null when selection is empty", () => {
    expect(deriveCameraFocusSelection(new Set(), "A")).toBeNull();
  });

  it("returns a selection descriptor with chain + resis", () => {
    const sel = deriveCameraFocusSelection(new Set([1, 2, 3]), "B");
    expect(sel).toEqual({ chain: "B", resis: [1, 2, 3] });
  });
});

describe("shouldAnimateCamera", () => {
  it("disables animation when prefers-reduced-motion is on", () => {
    expect(shouldAnimateCamera({ reducedMotion: true, hasSelection: true })).toBe(false);
  });

  it("disables animation when there is nothing to frame", () => {
    expect(shouldAnimateCamera({ reducedMotion: false, hasSelection: false })).toBe(false);
  });

  it("animates when user allows motion and has a selection", () => {
    expect(shouldAnimateCamera({ reducedMotion: false, hasSelection: true })).toBe(true);
  });
});

describe("nextFocusResidue (arrow-key keyboard navigation)", () => {
  const residues = [10, 11, 12, 13, 14, 20, 21];

  it("moves forward with ArrowRight", () => {
    expect(nextFocusResidue(residues, 12, "ArrowRight")).toBe(13);
  });

  it("moves backward with ArrowLeft", () => {
    expect(nextFocusResidue(residues, 12, "ArrowLeft")).toBe(11);
  });

  it("clamps at the end of the chain", () => {
    expect(nextFocusResidue(residues, 21, "ArrowRight")).toBe(21);
  });

  it("clamps at the start of the chain", () => {
    expect(nextFocusResidue(residues, 10, "ArrowLeft")).toBe(10);
  });

  it("returns the first residue when focus is not set yet", () => {
    expect(nextFocusResidue(residues, null, "ArrowRight")).toBe(10);
    expect(nextFocusResidue(residues, null, "ArrowLeft")).toBe(10);
  });

  it("skips ArrowUp/Down (reserved for row navigation, handled elsewhere)", () => {
    expect(nextFocusResidue(residues, 12, "ArrowUp")).toBe(12);
    expect(nextFocusResidue(residues, 12, "ArrowDown")).toBe(12);
  });

  it("noop when the residue list is empty", () => {
    expect(nextFocusResidue([], 1, "ArrowRight")).toBeNull();
  });
});

describe("clampSelectionToggle", () => {
  it("adds a residue when below the cap", () => {
    const result = clampSelectionToggle(new Set([1, 2]), 3, 20);
    expect(result.selected).toEqual(new Set([1, 2, 3]));
    expect(result.denied).toBe(false);
  });

  it("removes a residue that is already selected, even at cap", () => {
    const full = new Set(Array.from({ length: 20 }, (_, i) => i + 1));
    const result = clampSelectionToggle(full, 10, 20);
    expect(result.selected.has(10)).toBe(false);
    expect(result.denied).toBe(false);
  });

  it("denies adding past the cap", () => {
    const full = new Set(Array.from({ length: 20 }, (_, i) => i + 1));
    const result = clampSelectionToggle(full, 99, 20);
    expect(result.selected).toBe(full);
    expect(result.denied).toBe(true);
  });

  it("honours a custom cap", () => {
    const deny = clampSelectionToggle(new Set([1, 2, 3]), 4, 3);
    expect(deny.denied).toBe(true);
    const allow = clampSelectionToggle(new Set([1, 2]), 3, 3);
    expect(allow.denied).toBe(false);
    expect(allow.selected.has(3)).toBe(true);
  });
});

describe("highlightSelectedResidues (integration surface)", () => {
  it("invokes managers.structure.selection.fromSelectionQuery with 'set' mode", async () => {
    const fromSelectionQuery = vi.fn().mockResolvedValue(undefined);
    const plugin = {
      managers: {
        structure: {
          selection: { fromSelectionQuery },
          component: { updateRepresentationsTheme: vi.fn() },
        },
      },
    };
    const { highlightSelectedResidues } = await import("./residueSelection");
    await highlightSelectedResidues(plugin, new Set([5, 6]), { chainId: "A" });
    expect(fromSelectionQuery).toHaveBeenCalledTimes(1);
    const firstCall = fromSelectionQuery.mock.calls[0];
    expect(firstCall?.[0]).toBe("set");
  });

  it("clears the selection when the set is empty", async () => {
    const fromSelectionQuery = vi.fn().mockResolvedValue(undefined);
    const plugin = {
      managers: {
        structure: {
          selection: { fromSelectionQuery, clear: vi.fn() },
          component: { updateRepresentationsTheme: vi.fn() },
        },
      },
    };
    const { highlightSelectedResidues } = await import("./residueSelection");
    await highlightSelectedResidues(plugin, new Set(), { chainId: "A" });
    expect(plugin.managers.structure.selection.clear).toHaveBeenCalled();
  });
});

describe("animateCameraToSelection", () => {
  it("no-ops when selection is empty", async () => {
    const focus = vi.fn();
    const plugin = {
      managers: { camera: { focusLoci: focus, reset: vi.fn() } },
    };
    const { animateCameraToSelection } = await import("./residueSelection");
    await animateCameraToSelection(plugin, new Set(), { chainId: "A" });
    expect(focus).not.toHaveBeenCalled();
  });

  it("invokes the camera manager when selection is non-empty", async () => {
    const focusLoci = vi.fn();
    const plugin = {
      managers: {
        camera: { focusLoci, reset: vi.fn() },
      },
    };
    const { animateCameraToSelection } = await import("./residueSelection");
    await animateCameraToSelection(plugin, new Set([10, 11]), { chainId: "A" });
    expect(focusLoci).toHaveBeenCalled();
  });
});
