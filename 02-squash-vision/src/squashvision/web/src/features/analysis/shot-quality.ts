import type { ReviewShot } from "./shot-model";
export interface ScoreFactor { label: string; score: number; measurement: string }
export interface ShotGrade { quality: number | null; difficulty: number | null; partial: boolean; basis: "bounce" | "wall" | null; factors: ScoreFactor[]; reasons: string[]; difficultyReason: string }
const clamp = (v: number, low=0, high=10) => Math.max(low,Math.min(high,v));
const round = (v:number) => Math.round(clamp(v)*2)/2;

// Landing geometry gives placement families; distinguishing drops from boasts also needs wall-contact evidence.
export function placementFamily(shot: ReviewShot): "length" | "short" | null {
  const depth = shot.landing?.position?.[1];
  return depth === undefined ? null : depth >= 5.49 ? "length" : depth <= 2.6 ? "short" : null;
}
export function shotLabel(shot: ReviewShot): string {
  if (shot.type !== "unknown") return shot.type.charAt(0).toUpperCase()+shot.type.slice(1);
  const family=placementFamily(shot);
  return family === "length" ? "Length" : family === "short" ? "Short shot" : "Shot";
}

/** Transparent placement rubric v1. Heuristic targets, not a professional percentile. */
export function gradeShot(shot: ReviewShot, tinHeightM=.48): ShotGrade {
  const result: ShotGrade = { quality:null, difficulty:null, partial:false, basis:null, factors:[], reasons:[], difficultyReason:"Mark the opponent at contact and the landing to estimate retrieval pressure." };
  const landing = shot.landing?.position;
  const wall = shot.wall?.position;
  if (shot.origin === "automatic" && shot.confidence < .4) {
    result.reasons.push("Review this low-confidence detection before rating it."); return result;
  }
  if (wall && wall[1] <= tinHeightM) {
    result.quality=0;result.basis="wall";result.partial=!landing;
    result.reasons.push("Marked wall impact is at or below the tin. Check the marker; this is not a legal shot.");return result;
  }
  if (!landing && wall && shot.type !== "unknown") {
    result.basis="wall";result.partial=true;
    const [x,height]=wall, margin=Math.min(x,6.4-x);
    const tight=clamp(10*(1-margin/1.2));
    const low=clamp(10*(1-Math.max(0,height-tinHeightM-.25)/1.4));
    if (shot.type === "lob") {
      const clearance=clamp(10*(height-tinHeightM)/(3.4-tinHeightM));
      result.factors.push({label:"Wall clearance",score:round(clearance),measurement:`${height.toFixed(2)} m above floor`});
      result.quality=round(clearance);
    } else if (shot.type === "boast") {
      result.factors.push({label:"Wall height",score:round(low),measurement:`${height.toFixed(2)} m above floor`});
      result.quality=round(low);
    } else if (shot.type === "crosscourt") {
      const placement=clamp(10*(1-Math.max(0,Math.abs(x-3.2)-.6)/1.8));
      result.factors.push({label:"Crosscourt wall target",score:round(placement),measurement:`${x.toFixed(2)} m across front wall`});
      result.quality=round(placement);
    } else {
      result.factors.push({label:"Wall tightness",score:round(tight),measurement:`${Math.round(margin*100)} cm from wall corner`});
      if (shot.type === "drop") result.factors.push({label:"Wall height",score:round(low),measurement:`${height.toFixed(2)} m above floor`});
      result.quality=round(shot.type === "drop"?tight*.6+low*.4:tight);
    }
    result.reasons.push("Wall-placement score only. A first bounce was not observed; length, eventual retrieval and outcome are not scored.");
    return result;
  }
  const inferred = shot.type === "unknown" && shot.origin === "automatic" ? placementFamily(shot) : null;
  if (!landing || (shot.type === "unknown" && inferred === null) || (shot.origin === "automatic" && shot.confidence < .4)) {
    result.reasons.push(!landing ? "Mark the first landing to assess placement." : shot.type === "unknown" ? "Confirm the shot type to apply the right targets." : "Review this low-confidence detection before rating it.");
    return result;
  }
  if (inferred) { result.partial=true; result.reasons.push("Placement estimate from the tracked first bounce; shot type is unconfirmed."); }
  result.basis="bounce";
  const [x,depth] = landing;
  const margin = Math.min(x,6.4-x);
  const tight = clamp(10*(1-margin/1.2));
  result.factors.push({label:"Tightness",score:round(tight),measurement:`${Math.round(margin*100)} cm from side wall`});
  result.reasons.push(margin <= .3 ? "Tight to the side wall." : margin > .8 ? "Loose placement leaves space to attack." : "Room to bring it closer to the side wall.");
  const short = shot.type === "drop" || shot.type === "boast" || inferred === "short";
  const length = short ? clamp(10*(1-Math.max(0,depth-.6)/3)) : clamp(10*(1-Math.abs(depth-7.5)/3.5));
  result.factors.push({label:short ? "Shortness" : "Length",score:round(length),measurement:`${depth.toFixed(2)} m from front wall`});
  result.reasons.push(short ? depth <= 1.5 ? "Short first bounce." : "The ball lands deep for a short shot." : depth < 5.49 ? "Short length gives the opponent an opening." : depth > 9 ? "Very deep first bounce; check whether it comes out off the back wall." : "Good first-bounce depth.");
  const height = shot.wall?.position?.[1];
  if (typeof height === "number" && height <= tinHeightM) {
    result.quality=0; result.reasons=["Marked wall impact is at or below the tin. Check the marker; this is not a legal shot."]; return result;
  }
  let weighted = tight*.55 + length*.45;
  if (short || shot.type === "lob") {
    if (typeof height === "number") {
      const heightScore = short ? clamp(10*(1-Math.max(0,height-tinHeightM-.25)/1.4)) : clamp(10*(1-Math.abs(height-3.4)/2));
      result.factors.push({label:"Wall height",score:round(heightScore),measurement:`${height.toFixed(2)} m above floor`});
      weighted = tight*.45 + length*.35 + heightScore*.2;
    } else { result.partial=true; result.reasons.push("Wall height is unavailable; this score covers placement only."); }
  }
  result.quality=round(weighted);
  if (shot.opponentPosition && shot.landing) {
    const available = (shot.landing.timeUs-shot.contactUs)/1e6;
    if (available >= .1 && available <= 5) {
      const distance=Math.hypot(x-shot.opponentPosition[0],depth-shot.opponentPosition[1]);
      const demand=distance/available;
      result.difficulty=round(clamp(demand/6*10)*.8 + tight*.2);
      result.difficultyReason=`${distance.toFixed(1)} m to the first landing in ${available.toFixed(2)} s. A travel-pressure estimate; it does not predict whether the opponent can return the ball.`;
    }
  }
  return result;
}

export function coachingSummary(shots: ReviewShot[], tinHeightM=.48) {
  const rated=shots.map(shot=>({shot,grade:gradeShot(shot,tinHeightM)})).filter(s=>s.grade.quality !== null);
  const bounced=rated.filter(s=>s.grade.basis==="bounce" && s.shot.landing?.position);
  const wallOnlyCount=rated.length-bounced.length;
  const tinHits=rated.filter(s=>s.shot.wall?.position && s.shot.wall.position[1]<=tinHeightM);
  const drives=bounced.filter(s=>s.shot.type === "drive" || s.shot.type === "crosscourt");
  const short=drives.filter(s=>s.shot.landing!.position![1] < 5.49);
  const loose=bounced.filter(s=>s.shot.landing?.position && Math.min(s.shot.landing.position[0],6.4-s.shot.landing.position[0]) > .8);
  const insights:string[]=[];
  if(tinHits.length)insights.push(`${tinHits.length} marked wall impact${tinHits.length===1?" is":"s are"} at or below the tin. Verify these markers before drawing placement conclusions.`);
  if (short.length) insights.push(`${short.length} of ${drives.length} rated drives landed short of the short line. Practice driving into a deep target, then replay these examples.`);
  if (loose.length) insights.push(`${loose.length} of ${bounced.length} rated shots landed more than 80 cm from a side wall. Work on tighter placement.`);
  if (rated.length && !insights.length) insights.push(rated.every(s=>s.grade.quality!>=7 && s.grade.basis==="bounce")?"The marked sample is tight and well placed. Add more shots to check consistency across rallies.":"Replay the lowest-rated shots and compare their placement with the suggested targets.");
  return { ratedCount:rated.length, bounceRatedCount:bounced.length, wallOnlyCount, average:bounced.length ? bounced.reduce((v,s)=>v+s.grade.quality!,0)/bounced.length : null, insights, weakest:[...bounced].sort((a,b)=>a.grade.quality!-b.grade.quality!).slice(0,5) };
}
