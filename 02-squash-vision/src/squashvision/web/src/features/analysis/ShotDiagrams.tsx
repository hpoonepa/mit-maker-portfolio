import type { ReviewShot } from "./shot-model";
import { formatMatchTime } from "./analysis-model";
export function ShotDiagrams({shot,onSeek,tinHeightM=.48}:{shot:ReviewShot;onSeek:(us:number)=>void;tinHeightM?:number}) {
  const floor=shot.landing?.position,feet=shot.playerPosition,opponent=shot.opponentPosition,wall=shot.wall?.position;
  const marker=(x:number,y:number,label:string,time:number,color:string)=><g role="button" tabIndex={0} aria-label={label} onClick={()=>onSeek(time)} onKeyDown={e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();onSeek(time);}}} className="shot-diagram-marker"><title>{label}</title><circle cx={x} cy={y} r="34" fill="transparent"/><circle cx={x} cy={y} r="13" fill={color}/></g>;
  return <div className="shot-diagrams">
    <figure><figcaption>Court floor <span>First bounce & player positions</span></figcaption><svg viewBox="-25 -35 690 1040" role="group" aria-label="Selected shot court diagram">
      <rect x="0" y="0" width="640" height="975" className="shot-court-surface"/><path d="M0 546.5H640 M320 546.5V975 M0 546.5H162.5V711.5H0 M640 546.5H477.5V711.5H640" className="shot-court-lines"/>
      <text x="320" y="-12" textAnchor="middle">FRONT WALL</text>
      {feet&&<g><circle cx={feet[0]*100} cy={feet[1]*100} r="18" className="shot-player-position"/><text x={feet[0]*100+26} y={feet[1]*100+9}>Hitter</text></g>}
      {opponent&&<g><circle cx={opponent[0]*100} cy={opponent[1]*100} r="18" className="shot-opponent-position"/><text x={opponent[0]*100+26} y={opponent[1]*100+9}>Opponent</text></g>}
      {floor&&marker(floor[0]*100,floor[1]*100,`Landing X ${floor[0].toFixed(2)} m, depth ${floor[1].toFixed(2)} m`,shot.landing!.timeUs,"var(--shot-accent)")}
      {!floor&&<text x="320" y="420" textAnchor="middle">Landing not marked</text>}
    </svg><p>Player circles show feet, not ball contact.</p></figure>
    <figure><figcaption>Front wall <span>Impact height & width</span></figcaption><svg viewBox="-25 -30 690 520" role="group" aria-label="Selected shot front wall diagram">
      <rect x="0" y="0" width="640" height="457" className="shot-court-surface"/><path d="M0 279H640" className="shot-court-lines"/><rect x="0" y={457-tinHeightM*100} width="640" height={tinHeightM*100} className="shot-tin"/>
      <text x="15" y="270">SERVICE LINE · 1.78 m</text><text x="15" y="441">TIN</text>
      {wall&&marker(wall[0]*100,457-wall[1]*100,`Wall X ${wall[0].toFixed(2)} m, height ${wall[1].toFixed(2)} m`,shot.wall!.timeUs,"var(--shot-accent)")}
      {!wall&&<text x="320" y="180" textAnchor="middle">Wall position not measured</text>}
    </svg><p>{wall?`${wall[0].toFixed(2)} m across · ${wall[1].toFixed(2)} m high` : "Calibrate the wall, then mark its impact in video."}</p>
    <div className="shot-sequence">
      <button onClick={()=>onSeek(shot.contactUs)}>Racket contact <b>{formatMatchTime(shot.contactUs,true)}</b></button>
      <button disabled={!shot.wall} onClick={()=>shot.wall&&onSeek(shot.wall.timeUs)}>Front wall <b>{shot.wall?formatMatchTime(shot.wall.timeUs,true):"Not marked"}</b></button>
      <button disabled={!shot.landing} onClick={()=>shot.landing&&onSeek(shot.landing.timeUs)}>First landing <b>{shot.landing?formatMatchTime(shot.landing.timeUs,true):"Not marked"}</b></button>
    </div></figure>
  </div>;
}
