import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Point, ReviewShot, ShotReviewDocument, WallCalibration } from "./shot-model";
import { validWallCalibration } from "./wall-calibration";
const point = (v:unknown,w:number,h:number):boolean => v===null || Array.isArray(v)&&v.length===2&&v.every(n=>typeof n==="number"&&Number.isFinite(n))&&v[0]>=0&&v[0]<=w&&v[1]>=0&&v[1]<=h;
const time = (v:unknown):boolean => typeof v==="number"&&Number.isSafeInteger(v)&&v>=0;
export function decodeShotReview(value:unknown, revision:number, draft=false):ShotReviewDocument {
  if(!value||typeof value!=="object")throw new Error("Invalid saved shot review");
  const doc=value as ShotReviewDocument;
  if(!time(doc.version)||doc.reportRevision!==revision||!Array.isArray(doc.shots)||doc.shots.length>2000||new Set(doc.shots.map(s=>s.id)).size!==doc.shots.length)throw new Error("Invalid saved shot review");
  for(const s of doc.shots){
    if(!s||typeof s.id!=="string"||!/^[a-zA-Z0-9_-]{1,100}$/.test(s.id)||!time(s.contactUs)||![null,"A","B"].includes(s.hitter)||!["drive","crosscourt","drop","boast","lob","unknown"].includes(s.type)||!["automatic","reviewed"].includes(s.origin)||!Number.isFinite(s.confidence)||s.confidence<0||s.confidence>1||typeof s.notes!=="string"||s.notes.length>1000||!point(s.contactImage,1,1)||!point(s.playerPosition,6.4,9.75)||!point(s.opponentPosition,6.4,9.75))throw new Error("Invalid saved shot");
    for(const [kind,impact] of [["wall",s.wall],["landing",s.landing]] as const)if(impact!==null&&(!impact||!time(impact.timeUs)||(!draft&&impact.timeUs<=s.contactUs)||!point(impact.image,1,1)||!point(impact.position,6.4,kind==="wall"?4.57:9.75)))throw new Error("Invalid saved impact");
    if(!draft&&s.wall&&s.landing&&s.wall.timeUs>s.landing.timeUs)throw new Error("Invalid saved shot order");
  }
  if(doc.wallCalibration!==null&&(!doc.wallCalibration||!validWallCalibration(doc.wallCalibration)))throw new Error("Invalid wall calibration");
  return doc;
}
async function reviewRequest(url:string,revision:number,init?:RequestInit) {
  const response=await fetch(url,{...init,headers:{"Content-Type":"application/json",...init?.headers}});
  const value=await response.json();
  if(!response.ok)throw new Error(typeof value.message==="string"?value.message:"Shot review could not be saved. Please retry.");
  return decodeShotReview(value,revision);
}
export function useShotReview(matchId:string,revision:number) {
  const client=useQueryClient(), key=["shot-review",matchId,revision];
  const url=`/api/v1/matches/${encodeURIComponent(matchId)}/reports/${revision}/shot-review`;
  const query=useQuery({queryKey:key,enabled:revision>0,queryFn:({signal})=>reviewRequest(url,revision,{signal}),staleTime:30_000,retry:1});
  const save=useMutation({mutationFn:({shots,wallCalibration,expectedVersion}:{shots:ReviewShot[];wallCalibration:WallCalibration|null;expectedVersion:number})=>reviewRequest(url,revision,{method:"PUT",body:JSON.stringify({shots,wallCalibration,expectedVersion})}),onSuccess:doc=>client.setQueryData(key,doc)});
  return {query,save};
}
export function projectFloor(value:unknown,p:Point):Point|null {
  const c=value as {frameSize?:{width:number;height:number};result?:{imageToCourt?:number[][];calibrated?:boolean}}|null;
  const m=c?.result?.imageToCourt, size=c?.frameSize;
  if(!c?.result?.calibrated||!m||m.length!==3||m.some(r=>r.length!==3||r.some(v=>!Number.isFinite(v)))||!size?.width||!size.height)return null;
  const x=p[0]*size.width,y=p[1]*size.height,d=m[2][0]*x+m[2][1]*y+m[2][2];
  if(Math.abs(d)<1e-8)return null;
  const result:Point=[(m[0][0]*x+m[0][1]*y+m[0][2])/d,(m[1][0]*x+m[1][1]*y+m[1][2])/d];
  return point(result,6.4,9.75)?result:null;
}

export const shotDraftKey=(matchId:string,revision:number)=>`squashvision:shot-draft:${matchId}:${revision}`;
export function restoreShotDraft(matchId:string,revision:number):ShotReviewDocument|null {
  try {const value=sessionStorage.getItem(shotDraftKey(matchId,revision));return value?decodeShotReview(JSON.parse(value),revision,true):null;}catch{return null;}
}
