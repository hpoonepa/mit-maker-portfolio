import { describe, it, expect, vi } from "vitest";
import {
  navigationCommands,
  buildActionCommands,
  allStaticCommands,
} from "@/lib/commandPalette/registry";

/**
 * Static registry contract tests.
 *
 * The palette relies on two invariants:
 *   1. Every command id is unique (used as React key + dedupe key for recents)
 *   2. Every command has a callable `action`: the palette invokes this
 *      immediately on Enter, so a non-function here would be a runtime crash.
 */
describe("registry / navigationCommands", () => {
  it("exposes an id, title, group, and callable action for every entry", () => {
    for (const cmd of navigationCommands) {
      expect(typeof cmd.id).toBe("string");
      expect(cmd.id.length).toBeGreaterThan(0);
      expect(typeof cmd.title).toBe("string");
      expect(cmd.group).toBe("Navigation");
      expect(typeof cmd.action).toBe("function");
    }
  });

  it("has unique ids across all navigation entries", () => {
    const ids = navigationCommands.map((cmd) => cmd.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("covers every required destination from the spec", () => {
    const expectedTitles = [
      "Go to Dashboard",
      "Go to Projects",
      "Go to Jobs",
      "Go to Targets",
      "Go to Leaderboard",
      "Go to Usage",
      "Go to API Keys",
      "Go to Webhooks",
      "Go to Billing",
      "Go to Members",
      "Go to Audit Log",
    ];
    const actualTitles = navigationCommands.map((cmd) => cmd.title);
    for (const title of expectedTitles) {
      expect(actualTitles).toContain(title);
    }
  });

  it("dispatches navigation via the injected router", () => {
    const push = vi.fn();
    const dashboard = navigationCommands.find(
      (cmd) => cmd.title === "Go to Dashboard",
    );
    expect(dashboard).toBeDefined();
    dashboard!.action({ router: { push } });
    expect(push).toHaveBeenCalledWith("/home");
  });
});

describe("registry / buildActionCommands", () => {
  it("always includes context-free actions", () => {
    const commands = buildActionCommands({});
    const titles = commands.map((cmd) => cmd.title);
    expect(titles).toContain("Create Project");
    expect(titles).toContain("Upload Target");
    expect(titles).toContain("Create API Key");
    expect(titles).toContain("Invite Member");
  });

  it("omits Submit Job when no project context is present", () => {
    const commands = buildActionCommands({});
    expect(commands.map((cmd) => cmd.title)).not.toContain("Submit Job");
  });

  it("includes Submit Job when a project context is provided", () => {
    const commands = buildActionCommands({
      currentProjectId: "prj_123",
    });
    expect(commands.map((cmd) => cmd.title)).toContain("Submit Job");
  });

  it("assigns every action the Actions group", () => {
    const commands = buildActionCommands({ currentProjectId: "prj_123" });
    for (const cmd of commands) {
      expect(cmd.group).toBe("Actions");
      expect(typeof cmd.action).toBe("function");
    }
  });

  it("produces unique ids", () => {
    const commands = buildActionCommands({ currentProjectId: "prj_123" });
    const ids = commands.map((cmd) => cmd.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("registry / allStaticCommands", () => {
  it("merges navigation + actions and preserves unique ids", () => {
    const all = allStaticCommands({ currentProjectId: "prj_1" });
    const ids = all.map((cmd) => cmd.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
