/**
 * Tests for the Wave 8 onboarding state helpers.
 *
 * Coverage:
 *   - step navigation (next/prev/skippable)
 *   - resume policy (welcome / saved step / invited-to-org)
 *   - DB delegate (getProgress / setStep): uses an in-memory fake
 *   - localStorage cache round-trip
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ALL_STEPS,
  WIZARD_STEPS,
  PERSONAS,
  SKIPPABLE_WIZARD_STEPS,
  isWizardStep,
  nextStep,
  prevStep,
  isStepSkippable,
  stepHref,
  resolveResumeStep,
  getProgress,
  setStep,
  readClientCache,
  writeClientCache,
  clearClientCache,
  type OnboardingDelegate,
} from "../../lib/onboarding-state";

// ── Step taxonomy ────────────────────────────────────────────────────────────

describe("step taxonomy", () => {
  it("includes the six canonical wizard steps in order", () => {
    expect(WIZARD_STEPS).toEqual([
      "welcome",
      "create-org",
      "first-target",
      "first-job",
      "invite-team",
      "done",
    ]);
  });

  it("exposes three personas", () => {
    expect(PERSONAS.map((p) => p.id)).toEqual(["pi", "grad", "industry"]);
  });

  it("declares the three optional steps as skippable", () => {
    expect([...SKIPPABLE_WIZARD_STEPS].sort()).toEqual([
      "first-job",
      "first-target",
      "invite-team",
    ]);
  });

  it("ALL_STEPS is the union of legacy + wave8 steps", () => {
    for (const s of WIZARD_STEPS) {
      expect((ALL_STEPS as readonly string[]).includes(s)).toBe(true);
    }
  });
});

describe("isWizardStep", () => {
  it("accepts every canonical step", () => {
    for (const s of WIZARD_STEPS) expect(isWizardStep(s)).toBe(true);
  });
  it.each([null, undefined, "", "garbage", 42, {}])(
    "rejects non-step value %p",
    (v) => {
      expect(isWizardStep(v)).toBe(false);
    },
  );
});

describe("step navigation", () => {
  it("nextStep walks forward and returns null at the end", () => {
    expect(nextStep("welcome")).toBe("create-org");
    expect(nextStep("invite-team")).toBe("done");
    expect(nextStep("done")).toBeNull();
  });

  it("prevStep walks backward and returns null at the start", () => {
    expect(prevStep("welcome")).toBeNull();
    expect(prevStep("create-org")).toBe("welcome");
    expect(prevStep("done")).toBe("invite-team");
  });

  it("isStepSkippable matches the SKIPPABLE_WIZARD_STEPS set", () => {
    expect(isStepSkippable("welcome")).toBe(false);
    expect(isStepSkippable("create-org")).toBe(false);
    expect(isStepSkippable("first-target")).toBe(true);
    expect(isStepSkippable("first-job")).toBe(true);
    expect(isStepSkippable("invite-team")).toBe(true);
    expect(isStepSkippable("done")).toBe(false);
  });

  it("stepHref produces a /onboarding URL for each step", () => {
    for (const s of WIZARD_STEPS) {
      expect(stepHref(s)).toBe(`/onboarding/${s}`);
    }
  });
});

// ── Resume policy ────────────────────────────────────────────────────────────

describe("resolveResumeStep", () => {
  it("returns welcome for a brand-new user", () => {
    expect(
      resolveResumeStep({ savedStep: null, invitedToOrg: false }),
    ).toBe("welcome");
  });

  it("forwards an invited user past the create-org step", () => {
    expect(
      resolveResumeStep({ savedStep: null, invitedToOrg: true }),
    ).toBe("first-target");
    expect(
      resolveResumeStep({ savedStep: "welcome", invitedToOrg: true }),
    ).toBe("first-target");
    expect(
      resolveResumeStep({ savedStep: "create-org", invitedToOrg: true }),
    ).toBe("first-target");
  });

  it("respects the saved step for non-invited users", () => {
    expect(
      resolveResumeStep({ savedStep: "first-job", invitedToOrg: false }),
    ).toBe("first-job");
  });
});

// ── DB delegate ──────────────────────────────────────────────────────────────

interface Row {
  userId: string;
  orgId: string | null;
  currentStep: string;
  persona: string | null;
  completedAt: Date | null;
  lastUpdatedAt: Date;
}

function makeDelegate(seed: Row | null = null): OnboardingDelegate & {
  rows: Map<string, Row>;
} {
  const rows = new Map<string, Row>();
  if (seed) rows.set(seed.userId, seed);
  return {
    rows,
    async findUnique({ where: { userId } }) {
      return rows.get(userId) ?? null;
    },
    async upsert({ where: { userId }, update, create }) {
      const existing = rows.get(userId);
      if (existing) {
        rows.set(userId, {
          ...existing,
          currentStep: update.currentStep ?? existing.currentStep,
          persona: update.persona ?? existing.persona,
          orgId: update.orgId ?? existing.orgId,
          completedAt: update.completedAt ?? existing.completedAt,
          lastUpdatedAt: update.lastUpdatedAt,
        });
      } else {
        rows.set(userId, { ...create });
      }
      return rows.get(userId)!;
    },
  };
}

describe("getProgress / setStep", () => {
  it("getProgress returns null when the row is missing", async () => {
    const d = makeDelegate();
    expect(await getProgress(d, "u1")).toBeNull();
  });

  it("getProgress maps a row into a clean shape", async () => {
    const d = makeDelegate({
      userId: "u1",
      orgId: "org-1",
      currentStep: "first-job",
      persona: "pi",
      completedAt: null,
      lastUpdatedAt: new Date("2026-04-27T00:00:00Z"),
    });
    const p = await getProgress(d, "u1");
    expect(p).toMatchObject({
      userId: "u1",
      orgId: "org-1",
      currentStep: "first-job",
      persona: "pi",
      completed: false,
    });
  });

  it("getProgress sanitises unknown step / persona values", async () => {
    const d = makeDelegate({
      userId: "u1",
      orgId: null,
      currentStep: "garbage-step",
      persona: "celebrity",
      completedAt: null,
      lastUpdatedAt: new Date(),
    });
    const p = await getProgress(d, "u1");
    expect(p?.currentStep).toBe("welcome");
    expect(p?.persona).toBeNull();
  });

  it("setStep upserts and returns the persisted shape", async () => {
    const d = makeDelegate();
    const out = await setStep(d, "u1", { step: "create-org", persona: "grad" });
    expect(out).toMatchObject({
      userId: "u1",
      currentStep: "create-org",
      persona: "grad",
      completed: false,
    });
    expect(d.rows.get("u1")).toBeDefined();
  });

  it("setStep marks completion when step === done", async () => {
    const d = makeDelegate();
    const out = await setStep(d, "u1", { step: "done" });
    expect(out.completed).toBe(true);
  });

  it("setStep rejects unknown step strings", async () => {
    const d = makeDelegate();
    await expect(
      // @ts-expect-error: runtime check is the contract
      setStep(d, "u1", { step: "fake" }),
    ).rejects.toThrow(/unknown onboarding step/);
  });
});

// ── Client cache ─────────────────────────────────────────────────────────────

describe("client cache", () => {
  beforeEach(() => {
    if (!globalThis.localStorage) {
      const store = new Map<string, string>();
      Object.defineProperty(globalThis, "localStorage", {
        configurable: true,
        value: {
          clear: () => store.clear(),
          getItem: (key: string) => store.get(key) ?? null,
          removeItem: (key: string) => store.delete(key),
          setItem: (key: string, value: string) => store.set(key, value),
        },
      });
    }
    globalThis.localStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns null when nothing is stored", () => {
    expect(readClientCache()).toBeNull();
  });

  it("round-trips a valid cache entry", () => {
    writeClientCache({ step: "first-job", persona: "industry" });
    expect(readClientCache()).toEqual({
      step: "first-job",
      persona: "industry",
    });
  });

  it("ignores corrupt JSON", () => {
    globalThis.localStorage.setItem(
      "papercrane.onboarding.wave8.v1",
      "{not-json",
    );
    expect(readClientCache()).toBeNull();
  });

  it("ignores cache with an unknown step", () => {
    globalThis.localStorage.setItem(
      "papercrane.onboarding.wave8.v1",
      JSON.stringify({ step: "made-up", persona: "pi" }),
    );
    expect(readClientCache()).toBeNull();
  });

  it("normalises an unknown persona to null", () => {
    globalThis.localStorage.setItem(
      "papercrane.onboarding.wave8.v1",
      JSON.stringify({ step: "welcome", persona: "ceo" }),
    );
    expect(readClientCache()).toEqual({ step: "welcome", persona: null });
  });

  it("clearClientCache removes the entry", () => {
    writeClientCache({ step: "welcome", persona: null });
    clearClientCache();
    expect(readClientCache()).toBeNull();
  });
});
