/**
 * Preset targets: shape + content contract.
 *
 * The 3 presets are the "I don't have my own PDB yet" escape hatch of the
 * onboarding flow. They MUST:
 *   - cover the PRD's requested three targets (PD-L1, RBD, IL-7Rα)
 *   - each carry a real PDB id + hotspots + a one-line rationale
 *   - be keyed by a stable id so we can reference them from telemetry
 *
 * These tests intentionally pin the exact PDB ids and preset ids because
 * downstream analytics dashboards will group by those strings.
 */
import { describe, it, expect } from "vitest";
import {
  PRESET_TARGETS,
  getPresetTarget,
  type PresetTarget,
} from "@/lib/onboarding/presetTargets";

describe("PRESET_TARGETS", () => {
  it("exposes exactly three presets", () => {
    expect(PRESET_TARGETS).toHaveLength(3);
  });

  it("includes the PD-L1, SARS-CoV-2 RBD, and IL-7Rα targets by id", () => {
    const ids = PRESET_TARGETS.map((p) => p.id).sort();
    expect(ids).toEqual(["il7ra", "pdl1", "rbd"]);
  });

  it.each<[string, string]>([
    ["pdl1", "4ZQK"],
    ["rbd", "6M0J"],
    ["il7ra", "3UP1"],
  ])("maps preset %s to PDB %s", (id, pdb) => {
    const preset = PRESET_TARGETS.find((p) => p.id === id);
    expect(preset?.pdbId).toBe(pdb);
  });

  it("every preset has a non-empty name, rationale, hotspots, and chain", () => {
    for (const p of PRESET_TARGETS) {
      expect(p.name.length).toBeGreaterThan(0);
      expect(p.rationale.length).toBeGreaterThan(0);
      expect(p.hotspots.length).toBeGreaterThan(0);
      expect(p.chain.length).toBeGreaterThan(0);
    }
  });

  it("hotspot entries look like residue selectors (e.g. 'A56')", () => {
    const selector = /^[A-Z]\d+$/;
    for (const p of PRESET_TARGETS) {
      for (const h of p.hotspots) {
        expect(h).toMatch(selector);
      }
    }
  });

  it("preset ids are unique", () => {
    const ids = PRESET_TARGETS.map((p) => p.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("every preset object matches the PresetTarget contract", () => {
    for (const p of PRESET_TARGETS) {
      const _typed: PresetTarget = p;
      expect(typeof _typed.id).toBe("string");
      expect(typeof _typed.pdbId).toBe("string");
    }
  });
});

describe("getPresetTarget", () => {
  it("returns the preset for a known id", () => {
    const p = getPresetTarget("pdl1");
    expect(p?.pdbId).toBe("4ZQK");
  });

  it("returns undefined for an unknown id", () => {
    expect(getPresetTarget("nope")).toBeUndefined();
  });
});
