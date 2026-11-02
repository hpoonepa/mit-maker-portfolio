import { expect, it } from "vitest";
import { automaticShots, mergeShots, shotSpeed, type ReviewShot } from "./shot-model";
import type { PlaybackTimeline } from "./playback-model";

const shot:ReviewShot={id:"one",contactUs:1_000_000,hitter:"A",type:"drive",origin:"reviewed",confidence:1,contactImage:null,playerPosition:null,opponentPosition:null,wall:{timeUs:1_200_000,image:null,position:null},landing:null,notes:""};
const speed=(start:number,end:number,value:number)=>({intervalStartUs:start-10_000,timestampUs:start,proxyTimestampUs:start,proxyEndTimestampUs:end,sourceFrameIndex:1,speedMps:value});
const data=(ballSpeeds:PlaybackTimeline["ballSpeeds"])=>({ballSpeeds} as PlaybackTimeline);

it("keeps missing automatic evidence empty and lets a reviewed shot replace its candidate",()=>{
  expect(automaticShots(null)).toEqual([]);
  expect(mergeShots([{...shot,origin:"automatic",type:"unknown"}],[shot])).toEqual([shot]);
});

it("uses a robust flight median only when at least three complete outgoing measurements exist",()=>{
  const rows=[speed(1_010_000,1_020_000,10),speed(1_020_000,1_030_000,11),speed(1_030_000,1_040_000,90)];
  expect(shotSpeed(shot,null,data(rows)).value).toBe(11);
  expect(shotSpeed(shot,null,data(rows.slice(0,2))).value).toBeNull();
});

it("excludes incoming measurements at contact and clips coverage at the first impact",()=>{
  const rows=[speed(1_000_000,1_010_000,200),speed(1_010_000,1_020_000,10),speed(1_020_000,1_030_000,11)];
  expect(shotSpeed(shot,null,data(rows)).value).toBeNull();
  expect(shotSpeed(shot,null,data([speed(1_195_000,1_250_000,10)])).seconds).toBeCloseTo(.005);
  expect(shotSpeed(shot,1_015_000,data(rows)).value).toBeNull();
});
it("keeps wall and floor evidence for an unassigned hitter within the next-contact boundary",()=>{
  const contact=(id:string,kind:string,time:number,extra={})=>({id,kind,proxyTimestampUs:time,confidence:.7,hitter:null,shotContactId:null,ballImagePosition:[500,300],imageWidth:1280,imageHeight:720,playerPosition:null,floorPosition:null,...extra});
  const timeline={playerSamples:[],contacts:[contact("r1","racket",1_000_000),contact("w1","front_wall",1_300_000),contact("f1","floor",1_700_000,{floorPosition:[.2,6]}),contact("r2","racket",2_000_000),contact("w2","front_wall",2_300_000)]} as unknown as PlaybackTimeline;
  const shots=automaticShots(timeline);
  expect(shots[0].wall?.timeUs).toBe(1_300_000);
  expect(shots[0].landing?.position).toEqual([.2,6]);
  expect(shots[1].wall?.timeUs).toBe(2_300_000);
  expect(shots[1].landing).toBeNull();
});
