// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {QueryClient,QueryClientProvider} from "@tanstack/react-query";
import {afterEach,expect,it,vi} from "vitest";
import {LiveShotPanel} from "./LiveShotPanel";
import type {ReviewShot} from "./shot-model";

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const first:ReviewShot={id:"s1",contactUs:1_000_000,hitter:"A",type:"drive",origin:"reviewed",confidence:1,contactImage:null,playerPosition:null,opponentPosition:[4,5],wall:null,landing:{timeUs:2_000_000,image:null,position:[.15,7.5]},notes:""};
function setup(time=0){
  vi.stubGlobal("fetch",vi.fn(async()=>new Response(JSON.stringify({version:1,reportRevision:2,shots:[first,{...first,id:"s2",contactUs:3_000_000,landing:{timeUs:4_000_000,image:null,position:[2,4]}}],wallCalibration:null}))));
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}}),seek=vi.fn();
  const view=(currentTimeUs:number)=><QueryClientProvider client={client}><LiveShotPanel matchId="match" reportRevision={2} timeline={null} currentTimeUs={currentTimeUs} onSeek={seek}/></QueryClientProvider>;
  return{...render(view(time)),view,seek};
}
it("follows playback forward and backward without revealing a future shot's score",async()=>{
  const {rerender,view}=setup();
  await screen.findByRole("button",{name:"Next shot"});
  expect(screen.getByTestId("current-shot-quality")).toHaveTextContent("—");
  rerender(view(1_500_000));
  await waitFor(()=>expect(screen.getByTestId("current-shot-quality")).toHaveTextContent("9.5"));
  expect(screen.getByText("15 cm")).toBeInTheDocument();
  rerender(view(3_500_000));
  expect(screen.getByTestId("current-shot-quality")).toHaveTextContent("0.0");
  rerender(view(500_000));
  expect(screen.getByTestId("current-shot-quality")).toHaveTextContent("—");
});
it("seeks the adjacent shot directly from the live card",async()=>{
  const {seek}=setup(1_500_000);
  await waitFor(()=>expect(screen.getByTestId("current-shot-quality")).toHaveTextContent("9.5"));
  fireEvent.click(screen.getByRole("button",{name:"Next shot"}));
  expect(seek).toHaveBeenCalledWith(3_000_000);
  expect(screen.getByRole("button",{name:"Previous shot"})).toBeDisabled();
});
it("does not carry an old saved score into a region without tracking",async()=>{
  const {rerender,view}=setup(1_500_000);
  await waitFor(()=>expect(screen.getByTestId("current-shot-quality")).toHaveTextContent("9.5"));
  rerender(view(600_000_000));
  expect(screen.getByTestId("current-shot-quality")).toHaveTextContent("—");
});
