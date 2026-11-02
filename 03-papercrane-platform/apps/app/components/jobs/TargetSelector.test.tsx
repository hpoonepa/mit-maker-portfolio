import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TargetSelector } from "./TargetSelector";

const invalidate = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));
vi.mock("@/lib/trpc/client", () => ({trpc:{useUtils:()=>({targets:{list:{invalidate}}})}}));
vi.mock("@/components/targets/CreateTargetWizard", () => ({CreateTargetWizard:({onCreated}:{onCreated:(id:string)=>Promise<void>}) => <button onClick={()=>void onCreated("new-target")}>Save target & return to job</button>}));
afterEach(()=>{cleanup();vi.clearAllMocks();});

describe("target creation within a job", () => {
  it("refreshes saved targets and selects the new target without navigating away", async () => {
    const onSelect=vi.fn(); const onCreationChange=vi.fn();
    render(<TargetSelector targets={[]} selectedId={null} onSelect={onSelect} onCreationChange={onCreationChange} />);
    fireEvent.click(screen.getByRole("button",{name:"Add target"}));
    expect(screen.getByRole("region",{name:"Add target to this job"})).toBeTruthy();
    fireEvent.click(screen.getByRole("button",{name:"Save target & return to job"}));
    await waitFor(()=>expect(onSelect).toHaveBeenCalledWith("new-target"));
    expect(invalidate).toHaveBeenCalledOnce();
    expect(onCreationChange.mock.calls.map(call=>call[0])).toEqual([true,false]);
    expect(screen.queryByRole("region",{name:"Add target to this job"})).toBeNull();
  });
  it("lets users return to inputs without selecting or saving a target", () => {
    const onSelect=vi.fn();
    render(<TargetSelector targets={[]} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button",{name:"Add target"}));
    fireEvent.click(screen.getByRole("button",{name:"Back to job inputs"}));
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByRole("button",{name:"Add target"})).toBeTruthy();
  });
});
