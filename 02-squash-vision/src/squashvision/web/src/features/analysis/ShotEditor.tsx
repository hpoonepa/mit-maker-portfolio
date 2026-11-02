import { useEffect, useState } from "react";
import { SHOT_TYPES, type Point, type ReviewShot } from "./shot-model";
export type MarkKind="contact"|"wall"|"landing";
function PointFields({value,onChange,labels,maxY=9.75}:{value:Point|null;onChange:(v:Point|null)=>void;labels:[string,string];maxY?:number}) {
  const [text,setText]=useState<[string,string]>(value?[String(value[0]),String(value[1])]:["",""]);
  useEffect(()=>setText(value?[String(Number(value[0].toFixed(3))),String(Number(value[1].toFixed(3)))]:["",""]),[value?.[0],value?.[1]]);
  return <div className="shot-field-pair">{labels.map((label,i)=><label key={label}>{label}<input type="number" min="0" max={i?maxY:6.4} step="any" value={text[i]} placeholder="Unknown" onChange={e=>{const next:[string,string]=[...text];next[i]=e.target.value;setText(next);onChange(next.every(s=>s.trim()!==""&&Number.isFinite(Number(s)))?[Number(next[0]),Number(next[1])]:null);}}/></label>)}</div>;
}
export function ShotEditor({shot,onChange,onMark,onSave,onCancel,saving,error,durationUs}:{shot:ReviewShot;onChange:(s:ReviewShot)=>void;onMark:(kind:MarkKind)=>void;onSave:()=>void;onCancel:()=>void;saving:boolean;error:string|null;durationUs:number}) {
  const patch=(p:Partial<ReviewShot>)=>onChange({...shot,...p});
  return <form className="shot-editor" aria-busy={saving} onSubmit={e=>{e.preventDefault();onSave();}}><fieldset disabled={saving}>
    <header><h3>Review this shot</h3><span>Mark the ball on each paused frame.</span></header>
    <div className="shot-field-pair"><label>Player<select aria-label="Player" value={shot.hitter??""} onChange={e=>patch({hitter:e.target.value==="A"?"A":e.target.value==="B"?"B":null,playerPosition:null,opponentPosition:null})}><option value="">Unassigned</option><option>A</option><option>B</option></select></label><label>Shot type<select aria-label="Shot type" value={shot.type} onChange={e=>patch({type:e.target.value as ReviewShot["type"]})}>{SHOT_TYPES.map(([v,label])=><option key={v} value={v}>{label}</option>)}</select></label></div>
    <div className="shot-marker-row"><label>Contact time (seconds)<input type="number" required min="0" max={(durationUs-1)/1e6} step="0.000001" value={shot.contactUs/1e6} onChange={e=>patch({contactUs:Math.round(Number(e.target.value)*1e6),contactImage:null,playerPosition:null,opponentPosition:null})}/></label><button type="button" onClick={()=>onMark("contact")}>Mark contact on video</button></div>
    <div className="shot-marker-row"><label>Wall time (seconds)<input type="number" min="0" max={(durationUs-1)/1e6} step="0.000001" value={shot.wall?shot.wall.timeUs/1e6:""} placeholder="Optional" onChange={e=>patch({wall:e.target.value===""?null:{timeUs:Math.round(Number(e.target.value)*1e6),image:shot.wall?.image??null,position:shot.wall?.position??null}})}/></label><button type="button" onClick={()=>onMark("wall")}>Mark wall on video</button></div>
    {shot.wall?.position&&<p className="shot-measurement">Wall impact: {shot.wall.position[0].toFixed(2)} m across · {shot.wall.position[1].toFixed(2)} m high</p>}
    <div className="shot-marker-row"><label>Landing time (seconds)<input type="number" min="0" max={(durationUs-1)/1e6} step="0.000001" value={shot.landing?shot.landing.timeUs/1e6:""} placeholder="Optional" onChange={e=>patch({landing:e.target.value===""?null:{timeUs:Math.round(Number(e.target.value)*1e6),image:shot.landing?.image??null,position:shot.landing?.position??null}})}/></label><button type="button" onClick={()=>onMark("landing")}>Mark landing on video</button></div>
    {shot.landing&&<PointFields value={shot.landing.position} labels={["Landing X (m)","Landing depth (m)"]} onChange={position=>patch({landing:{...shot.landing!,position}})}/>}
    <details><summary>Player positions at contact</summary><p>Use observed floor positions. Leave unknown positions empty.</p><PointFields value={shot.playerPosition} labels={["Hitter X (m)","Hitter depth (m)"]} onChange={playerPosition=>patch({playerPosition})}/><PointFields value={shot.opponentPosition} labels={["Opponent X (m)","Opponent depth (m)"]} onChange={opponentPosition=>patch({opponentPosition})}/></details>
    <label>Shot notes<textarea maxLength={1000} value={shot.notes} placeholder="What would you change next time?" onChange={e=>patch({notes:e.target.value})}/></label>
    {error&&<p role="alert" className="shot-error">{error}</p>}
    <footer><button type="submit" className="shot-primary" disabled={saving}>{saving?"Saving…":"Save shot"}</button><button type="button" onClick={onCancel} disabled={saving}>Cancel</button><span>Reviewed estimates · saved with this report</span></footer>
  </fieldset></form>;
}
