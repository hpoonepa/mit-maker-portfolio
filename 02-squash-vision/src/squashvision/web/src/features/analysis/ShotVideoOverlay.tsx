import { useEffect, useRef, useState } from "react";
import type { Point } from "./shot-model";
export interface VideoDot {point:Point;label:string}
export function ShotVideoOverlay({active,prompt,dots,onPick,onCancel,width,height}:{active:boolean;prompt:string;dots:VideoDot[];onPick:(p:Point)=>void;onCancel:()=>void;width:number;height:number}) {
  const ref=useRef<SVGSVGElement>(null),[cursor,setCursor]=useState<Point>([.5,.5]);
  useEffect(()=>{if(active)ref.current?.focus();},[active,prompt]);
  return <><svg ref={ref} className={`shot-video-overlay${active?" is-picking":""}`} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet" tabIndex={active?0:undefined} role={active?"application":undefined} aria-label={active?`${prompt}. Click the ball, or use arrow keys and Enter. Escape cancels.`:undefined}
    onPointerDown={e=>{if(!active)return;const matrix=e.currentTarget.getScreenCTM();if(!matrix)return;const point=new DOMPoint(e.clientX,e.clientY).matrixTransform(matrix.inverse());const p:Point=[point.x/width,point.y/height];if(p.every(v=>v>=0&&v<=1)){e.stopPropagation();onPick(p);}}}
    onKeyDown={e=>{if(!active)return;if(["ArrowLeft","ArrowRight","ArrowUp","ArrowDown","Enter","Escape"," "].includes(e.key)){e.preventDefault();e.stopPropagation();}const step=e.shiftKey?10:1;if(e.key==="Enter")onPick(cursor);else if(e.key==="Escape")onCancel();else if(e.key.startsWith("Arrow"))setCursor(([x,y])=>[Math.max(0,Math.min(1,x+(e.key==="ArrowRight"?step:e.key==="ArrowLeft"?-step:0)/width)),Math.max(0,Math.min(1,y+(e.key==="ArrowDown"?step:e.key==="ArrowUp"?-step:0)/height))]);}}>
    {dots.map((dot,i)=><g key={`${dot.label}-${i}`}><circle cx={dot.point[0]*width} cy={dot.point[1]*height} r="12"/><text x={dot.point[0]*width+18} y={dot.point[1]*height-14}>{dot.label}</text></g>)}
    {active&&<g className="shot-crosshair"><path d={`M${cursor[0]*width-18} ${cursor[1]*height}h36 M${cursor[0]*width} ${cursor[1]*height-18}v36`}/></g>}
  </svg>{active&&<div className="shot-pick-prompt" role="status"><span>{prompt}</span><button type="button" onClick={onCancel}>Cancel marking</button></div>}</>;
}
