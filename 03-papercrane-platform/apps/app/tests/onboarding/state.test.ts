/**
 * Onboarding state machine tests.
 *
 * The onboarding wizard is a 5-step linear flow with a few wrinkles:
 *   1. two steps ("first-target", "first-job") are *skippable*: skipping
 *      must still advance the step pointer and be recorded so we can show
 *      a "finish later" nudge on the dashboard
 *   2. state persists to localStorage so a refresh or a context switch
 *      doesn't lose the in-progress org/target payload
 *   3. the signup + tier steps are handled upstream (auth flow hands us a
 *      user that *may or may not* already have an org); the machine's first
 *      real step is "welcome"
 *
 * These tests pin the transitions + persistence contract so the React layer
 * can treat the machine as a black box.
 */
import { describe, it, expect, beforeEach } from "vitest";
import {
  ONBOARDING_STEPS,
  createOnboardingState,
  advance,
  goBack,
  skip,
  updateOrgDraft,
  updateTargetDraft,
  markSubmitted,
  loadState,
  saveState,
  clearState,
  isStepSkippable,
  progressPercent,
  type OnboardingState,
  type OnboardingStep,
} from "@/lib/onboarding/state";

// jsdom gives us a localStorage shim; reset it between tests so persistence
// cases start from a clean slate.
beforeEach(() => {
  globalThis.localStorage.clear();
});

describe("ONBOARDING_STEPS", () => {
  it("lists the 5 wizard steps in canonical order", () => {
    expect(ONBOARDING_STEPS).toEqual([
      "welcome",
      "create-org",
      "first-target",
      "first-job",
      "done",
    ]);
  });
});

describe("createOnboardingState", () => {
  it("starts at welcome with empty drafts and no skips", () => {
    const s = createOnboardingState();
    expect(s.step).toBe("welcome");
    expect(s.orgDraft).toEqual({ name: "", type: "lab" });
    expect(s.targetDraft).toBeNull();
    expect(s.skipped).toEqual([]);
    expect(s.submittedJobId).toBeNull();
  });
});

describe("advance", () => {
  it("moves welcome → create-org", () => {
    const s = advance(createOnboardingState());
    expect(s.step).toBe("create-org");
  });

  it("moves create-org → first-target", () => {
    const s = advance({ ...createOnboardingState(), step: "create-org" });
    expect(s.step).toBe("first-target");
  });

  it("moves first-target → first-job", () => {
    const s = advance({ ...createOnboardingState(), step: "first-target" });
    expect(s.step).toBe("first-job");
  });

  it("moves first-job → done", () => {
    const s = advance({ ...createOnboardingState(), step: "first-job" });
    expect(s.step).toBe("done");
  });

  it("is a no-op at done (terminal state)", () => {
    const terminal = { ...createOnboardingState(), step: "done" as const };
    expect(advance(terminal).step).toBe("done");
  });
});

describe("goBack", () => {
  it("moves create-org → welcome", () => {
    const s = goBack({ ...createOnboardingState(), step: "create-org" });
    expect(s.step).toBe("welcome");
  });

  it("is a no-op at welcome (first step)", () => {
    const s = goBack(createOnboardingState());
    expect(s.step).toBe("welcome");
  });

  it("moves first-job → first-target", () => {
    const s = goBack({ ...createOnboardingState(), step: "first-job" });
    expect(s.step).toBe("first-target");
  });
});

describe("skip", () => {
  it("records the current step and advances", () => {
    const start = { ...createOnboardingState(), step: "first-target" as const };
    const s = skip(start);
    expect(s.step).toBe("first-job");
    expect(s.skipped).toContain("first-target");
  });

  it("refuses to skip non-skippable steps (welcome stays put)", () => {
    const start = createOnboardingState();
    const s = skip(start);
    expect(s.step).toBe("welcome");
    expect(s.skipped).toEqual([]);
  });

  it("does not double-record a step if skip is called twice", () => {
    const start = { ...createOnboardingState(), step: "first-target" as const };
    const once = skip(start);
    // Manually put us back on first-target and skip again. Whether the user
    // can actually get back here via the UI is a separate concern; the state
    // machine must be idempotent.
    const back: OnboardingState = { ...once, step: "first-target" };
    const twice = skip(back);
    expect(twice.skipped.filter((s) => s === "first-target")).toHaveLength(1);
  });
});

describe("isStepSkippable", () => {
  it("returns true for first-target and first-job", () => {
    expect(isStepSkippable("first-target")).toBe(true);
    expect(isStepSkippable("first-job")).toBe(true);
  });

  it("returns false for welcome, create-org, and done", () => {
    expect(isStepSkippable("welcome")).toBe(false);
    expect(isStepSkippable("create-org")).toBe(false);
    expect(isStepSkippable("done")).toBe(false);
  });
});

describe("updateOrgDraft", () => {
  it("merges partial updates into the existing draft", () => {
    const s = updateOrgDraft(createOnboardingState(), { name: "Acme Bio" });
    expect(s.orgDraft).toEqual({ name: "Acme Bio", type: "lab" });
  });

  it("lets callers change the org type", () => {
    const s = updateOrgDraft(createOnboardingState(), { type: "industry" });
    expect(s.orgDraft.type).toBe("industry");
  });
});

describe("updateTargetDraft", () => {
  it("sets the target draft from a preset selection", () => {
    const s = updateTargetDraft(createOnboardingState(), {
      source: "preset",
      presetId: "pdl1",
      pdbId: "4ZQK",
    });
    expect(s.targetDraft).toEqual({
      source: "preset",
      presetId: "pdl1",
      pdbId: "4ZQK",
    });
  });

  it("sets the target draft from an uploaded file", () => {
    const s = updateTargetDraft(createOnboardingState(), {
      source: "upload",
      fileName: "my_target.pdb",
    });
    expect(s.targetDraft).toEqual({
      source: "upload",
      fileName: "my_target.pdb",
    });
  });

  it("accepts null to clear", () => {
    const seeded = updateTargetDraft(createOnboardingState(), {
      source: "preset",
      presetId: "rbd",
      pdbId: "6M0J",
    });
    const cleared = updateTargetDraft(seeded, null);
    expect(cleared.targetDraft).toBeNull();
  });
});

describe("markSubmitted", () => {
  it("records the submitted job id", () => {
    const s = markSubmitted(createOnboardingState(), "job_abc123");
    expect(s.submittedJobId).toBe("job_abc123");
  });
});

describe("progressPercent", () => {
  it.each<[OnboardingStep, number]>([
    ["welcome", 0],
    ["create-org", 25],
    ["first-target", 50],
    ["first-job", 75],
    ["done", 100],
  ])("returns %i%% for step %s", (step, pct) => {
    expect(progressPercent(step)).toBe(pct);
  });
});

describe("localStorage persistence", () => {
  it("loadState returns null when nothing is saved", () => {
    expect(loadState()).toBeNull();
  });

  it("saveState + loadState roundtrips the full state", () => {
    const s = markSubmitted(
      updateTargetDraft(
        updateOrgDraft(
          { ...createOnboardingState(), step: "first-job" },
          { name: "Acme Bio", type: "lab" },
        ),
        { source: "preset", presetId: "pdl1", pdbId: "4ZQK" },
      ),
      "job_abc123",
    );
    saveState(s);
    expect(loadState()).toEqual(s);
  });

  it("loadState returns null if the stored payload is malformed JSON", () => {
    globalThis.localStorage.setItem("papercrane.onboarding.v1", "{not json");
    expect(loadState()).toBeNull();
  });

  it("loadState returns null if the stored step is unknown", () => {
    globalThis.localStorage.setItem(
      "papercrane.onboarding.v1",
      JSON.stringify({ step: "mystery-step" }),
    );
    expect(loadState()).toBeNull();
  });

  it("clearState removes the key", () => {
    saveState(createOnboardingState());
    clearState();
    expect(loadState()).toBeNull();
  });
});
