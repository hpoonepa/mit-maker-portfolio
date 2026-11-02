// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { ShotReviewPanel } from "./ShotReviewPanel";
import type { ReviewShot } from "./shot-model";
afterEach(()=>{cleanup();vi.unstubAllGlobals();sessionStorage.clear();});
const sample:ReviewShot={id:"s1",contactUs:1_000_000,hitter:"A",type:"drive",origin:"reviewed",confidence:1,contactImage:[.2,.3],playerPosition:[1,5],opponentPosition:null,wall:null,landing:{timeUs:2_000_000,image:null,position:[.15,7.5]},notes:""};
function setup(shots:ReviewShot[]=[], failSave=false, videoTime=1) {
  const fetch=vi.fn(async (_url:unknown, init?:RequestInit)=>{
    if(String(_url).endsWith("/calibration"))return new Response(JSON.stringify({}),{status:404});
    if(init?.method==="PUT"&&failSave)return new Response(JSON.stringify({message:"Shot review changed in another tab. Reload the saved review before trying again."}),{status:409});
    const body=init?.body?JSON.parse(String(init.body)):null;
    return new Response(JSON.stringify({version:body?1:0,reportRevision:2,shots:body?.shots??shots,wallCalibration:null}),{status:200});
  });
  vi.stubGlobal("fetch",fetch);
  const onSeek=vi.fn();const pause=vi.fn();
  const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});
  const view=render(<QueryClientProvider client={client}><ShotReviewPanel matchId="match" reportRevision={2} timeline={null} currentTimeUs={1_000_000} durationUs={65_000_000} videoRef={{current:{pause,parentElement:null,currentTime:videoTime} as unknown as HTMLVideoElement}} onSeek={onSeek}/></QueryClientProvider>);
  return {fetch,onSeek,pause,client,...view};
}
it("explains empty detections and lets a paused user create and save a shot",async()=>{
  const {fetch,pause}=setup();
  await screen.findByRole("button",{name:"Add shot at current frame"});
  await waitFor(()=>expect(screen.getByRole("button",{name:"Add shot at current frame"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"Add shot at current frame"}));
  expect(pause).toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Shot type"),{target:{value:"drive"}});
  fireEvent.change(screen.getByLabelText("Player"),{target:{value:"A"}});
  fireEvent.change(screen.getByLabelText("Landing time (seconds)"),{target:{value:"2"}});
  fireEvent.change(screen.getByLabelText("Landing X (m)"),{target:{value:"0.15"}});
  fireEvent.change(screen.getByLabelText("Landing depth (m)"),{target:{value:"7.5"}});
  fireEvent.click(screen.getByRole("button",{name:"Save shot"}));
  await waitFor(()=>expect(fetch.mock.calls.some(([,init])=>init?.method==="PUT")).toBe(true));
  const saved=JSON.parse(String(fetch.mock.calls.find(([,init])=>init?.method==="PUT")![1]!.body));
  expect(saved.shots[0].landing.position).toEqual([.15,7.5]);
  expect(saved.shots[0].origin).toBe("reviewed");
  await screen.findByText("Saved locally");
});
it("shows explained scores and seeks the exact saved shot",async()=>{
  const {onSeek}=setup([sample]);
  fireEvent.click(await screen.findByRole("button",{name:/Shot 1.*Drive/i}));
  expect(onSeek).toHaveBeenCalledWith(1_000_000);
  expect(screen.getByText("Tightness")).toBeInTheDocument();
  expect(screen.getByText(/Mark the opponent at contact/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:/First landing.*0:02/}));
  expect(onSeek).toHaveBeenLastCalledWith(2_000_000);
});
it("keeps the editor and unsaved changes visible when a concurrent save conflicts",async()=>{
  setup([sample],true);
  await screen.findByRole("button",{name:/Shot 1.*Drive/i});
  fireEvent.click(screen.getByRole("button",{name:"Edit shot"}));
  fireEvent.change(screen.getByLabelText("Shot notes"),{target:{value:"My unsaved note"}});
  fireEvent.click(screen.getByRole("button",{name:"Save shot"}));
  await screen.findByText(/changed in another tab/);
  expect(screen.getByLabelText("Shot notes")).toHaveValue("My unsaved note");
});

it("retains the edit's base version after a background refresh",async()=>{
  const {client,fetch}=setup([sample]);
  await screen.findByRole("button",{name:/Shot 1.*Drive/i});
  fireEvent.click(screen.getByRole("button",{name:"Edit shot"}));
  client.setQueryData(["shot-review","match",2],{version:2,reportRevision:2,shots:[{...sample,notes:"Other tab"}],wallCalibration:null});
  fireEvent.change(screen.getByLabelText("Shot notes"),{target:{value:"My edit"}});
  fireEvent.click(screen.getByRole("button",{name:"Save shot"}));
  await waitFor(()=>expect(fetch.mock.calls.some(([,init])=>init?.method==="PUT")).toBe(true));
  const body=JSON.parse(String(fetch.mock.calls.find(([,init])=>init?.method==="PUT")![1]!.body));
  expect(body.expectedVersion).toBe(0);
});

it("accepts exact frame microseconds and projected millimetre coordinates",async()=>{
  setup([{...sample,contactUs:1_033_334,landing:{timeUs:2_033_334,image:null,position:[.153,7.567]}}]);
  await screen.findByRole("button",{name:/Shot 1.*Drive/i});
  fireEvent.click(screen.getByRole("button",{name:"Edit shot"}));
  expect((screen.getByLabelText("Contact time (seconds)") as HTMLInputElement).checkValidity()).toBe(true);
  expect((screen.getByLabelText("Landing X (m)") as HTMLInputElement).checkValidity()).toBe(true);
});

it("clears old identity and timestamp positions when the contact is corrected",async()=>{
  setup([{...sample,opponentPosition:[5,5]}]);
  await screen.findByRole("button",{name:/Shot 1.*Drive/i});
  fireEvent.click(screen.getByRole("button",{name:"Edit shot"}));
  fireEvent.change(screen.getByLabelText("Player"),{target:{value:"B"}});
  fireEvent.click(screen.getByText("Player positions at contact"));
  expect(screen.getByLabelText("Opponent X (m)")).toHaveValue(null);
  expect(screen.getByLabelText("Hitter X (m)")).toHaveValue(null);
});

it("restores an unsaved report-scoped draft after the panel unmounts",async()=>{
  const first=setup([sample]);
  await screen.findByRole("button",{name:/Shot 1.*Drive/i});
  fireEvent.click(screen.getByRole("button",{name:"Edit shot"}));
  fireEvent.change(screen.getByLabelText("Shot notes"),{target:{value:"Keep this draft"}});
  first.unmount();
  setup([sample]);
  expect(await screen.findByLabelText("Shot notes")).toHaveValue("Keep this draft");
});

it("disables further edits while a save is pending",async()=>{
  const {fetch}=setup([sample]);
  await screen.findByRole("button",{name:/Shot 1.*Drive/i});
  fireEvent.click(screen.getByRole("button",{name:"Edit shot"}));
  fetch.mockImplementationOnce(()=>new Promise(()=>{}));
  fireEvent.click(screen.getByRole("button",{name:"Save shot"}));
  await waitFor(()=>expect(screen.getByLabelText("Shot notes")).toBeDisabled());
  expect(screen.getByRole("button",{name:"Mark contact on video"})).toBeDisabled();
});

it("marks the actual paused video time when React's displayed clock lags a seek",async()=>{
  setup([],false,1.033334);
  await waitFor(()=>expect(screen.getByRole("button",{name:"Add shot at current frame"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"Add shot at current frame"}));
  expect(screen.getByLabelText("Contact time (seconds)")).toHaveValue(1.033334);
});
