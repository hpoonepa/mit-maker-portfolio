import { useEffect, useMemo, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { formatMatchTime } from "./analysis-model";
import type { PlaybackTimeline } from "./playback-model";
import { automaticShots, imagePoint, mergeShots, shotSpeed, type Point, type ReviewShot, type WallCalibration } from "./shot-model";
import { gradeShot, coachingSummary, shotLabel } from "./shot-quality";
import { projectWall, validWallCalibration } from "./wall-calibration";
import { projectFloor, useShotReview, restoreShotDraft, shotDraftKey } from "./shot-review-data";
import { ShotEditor, type MarkKind } from "./ShotEditor";
import { ShotDiagrams } from "./ShotDiagrams";
import { ShotVideoOverlay, type VideoDot } from "./ShotVideoOverlay";
import "./ShotReviewPanel.css";

interface Props {matchId:string;reportRevision:number;timeline:PlaybackTimeline|null;currentTimeUs:number;durationUs:number;videoRef:RefObject<HTMLVideoElement|null>;onSeek:(us:number)=>void;onDirtyChange?:(dirty:boolean)=>void}
const title=shotLabel;
const wallSteps=["1 / 4 · Click the front wall’s LEFT floor corner","2 / 4 · Click the front wall’s RIGHT floor corner","3 / 4 · Click the RIGHT end of the service line","4 / 4 · Click the LEFT end of the service line"];
const rating=(value:number|null)=>value===null?"—":value.toFixed(1);

export function ShotReviewPanel({matchId,reportRevision,timeline,currentTimeUs,durationUs,videoRef,onSeek,onDirtyChange}:Props) {
  const {query,save}=useShotReview(matchId,reportRevision);
  const [selectedId,setSelectedId]=useState<string|null>(null),[filter,setFilter]=useState("all");
  const [restored]=useState(()=>restoreShotDraft(matchId,reportRevision));
  const [editVersion,setEditVersion]=useState<number|null>(restored?.version??null);
  const [draft,setDraft]=useState<ReviewShot|null>(restored?.shots[0]??null),[marking,setMarking]=useState<MarkKind|null>(null);
  const [calibrationPoints,setCalibrationPoints]=useState<Point[]|null>(null),[tin,setTin]=useState(.48);
  const [error,setError]=useState<string|null>(null),[saved,setSaved]=useState(false);
  const [videoHost,setVideoHost]=useState<HTMLElement|null>(null);
  const floor=useQuery({queryKey:["shot-review-floor",matchId,timeline?.calibrationRevision],queryFn:async()=>{const r=await fetch(`/api/v1/matches/${encodeURIComponent(matchId)}/calibration`);return r.ok?r.json():null;},staleTime:60_000,retry:false});
  useEffect(()=>{try{const key=shotDraftKey(matchId,reportRevision);if(draft&&editVersion!==null)sessionStorage.setItem(key,JSON.stringify({version:editVersion,reportRevision,shots:[draft],wallCalibration:null}));else if(!draft)sessionStorage.removeItem(key);}catch{setError("This browser could not preserve the draft. Save it before leaving this page.");}},[draft,editVersion,matchId,reportRevision]);
  useEffect(()=>setVideoHost(videoRef.current?.parentElement??null),[videoRef,reportRevision]);
  useEffect(()=>{onDirtyChange?.(draft!==null||calibrationPoints!==null);return()=>onDirtyChange?.(false);},[draft,calibrationPoints,onDirtyChange]);
  useEffect(()=>{if(!draft&&!calibrationPoints)return;const warn=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue="";};window.addEventListener("beforeunload",warn);return()=>window.removeEventListener("beforeunload",warn);},[draft,calibrationPoints]);
  const auto=useMemo(()=>automaticShots(timeline,query.data?.wallCalibration),[timeline,query.data?.wallCalibration]);
  const shots=useMemo(()=>mergeShots(auto,query.data?.shots??[]),[auto,query.data?.shots]);
  const selected=shots.find(s=>s.id===selectedId)??shots[0]??null;
  const shown=shots.filter(s=>filter==="all"||s.hitter===filter);
  const wallCalibration=query.data?.wallCalibration??null;
  const grade=selected?gradeShot(selected,wallCalibration?.tinHeightM):null;
  const coaching=useMemo(()=>coachingSummary(shots,wallCalibration?.tinHeightM),[shots,wallCalibration?.tinHeightM]);
  const selectedIndex=selected?shots.findIndex(s=>s.id===selected.id):-1;
  const speed=selected?shotSpeed(selected,shots[selectedIndex+1]?.contactUs??null,timeline):null;
  const cancelDraft=()=>{setDraft(null);setMarking(null);setError(null);};
  const seek=(us:number)=>{videoRef.current?.pause();onSeek(us);};
  const pausedTimeUs=()=>{const seconds=videoRef.current?.currentTime;return seconds!==undefined&&Number.isFinite(seconds)?Math.round(seconds*1_000_000):currentTimeUs;};
  const choose=(shot:ReviewShot)=>{if(draft&&!window.confirm("Discard the unsaved shot edits?"))return;cancelDraft();setSelectedId(shot.id);seek(shot.contactUs);};
  const begin=()=>{if(draft&&!window.confirm("Discard the unsaved shot edits?"))return;videoRef.current?.pause();setEditVersion(query.data?.version??0);setSaved(false);setError(null);setDraft({id:`review-${crypto.randomUUID()}`,contactUs:pausedTimeUs(),hitter:null,type:"unknown",origin:"reviewed",confidence:1,contactImage:null,playerPosition:null,opponentPosition:null,wall:null,landing:null,notes:""});};
  const startMark=(kind:MarkKind)=>{videoRef.current?.pause();setMarking(kind);setError(null);videoHost?.scrollIntoView({behavior:"smooth",block:"center"});};
  const pick=(point:Point)=>{
    if(calibrationPoints!==null){setCalibrationPoints([...calibrationPoints,point]);return;}
    if(!draft||!marking)return;
    const timeUs=pausedTimeUs();
    if(marking!=="contact"&&timeUs<=draft.contactUs){setError("Move the video after racket contact, then mark this impact.");setMarking(null);return;}
    if(marking==="contact")setDraft({...draft,contactUs:timeUs,contactImage:point,...(timeUs!==draft.contactUs?{playerPosition:null,opponentPosition:null}:{})});
    else if(marking==="wall")setDraft({...draft,wall:{timeUs,image:point,position:wallCalibration?projectWall(wallCalibration,point):null}});
    else setDraft({...draft,landing:{timeUs,image:point,position:projectFloor(floor.data,point)}});
    setMarking(null);
  };
  const persist=async(reviewed:ReviewShot[],calibration:WallCalibration|null)=>{
    if(!query.data)throw new Error("Load the saved review before saving changes.");
    return save.mutateAsync({expectedVersion:editVersion??query.data.version,shots:reviewed,wallCalibration:calibration});
  };
  const saveShot=async()=>{
    if(!draft)return;
    try{setError(null);await persist([...(query.data?.shots??[]).filter(s=>s.id!==draft.id),{...draft,origin:"reviewed",confidence:1}],wallCalibration);setSelectedId(draft.id);setDraft(null);setMarking(null);setSaved(true);}catch(e){setError(e instanceof Error?e.message:"Could not save this shot.");}
  };
  const saveCalibration=async()=>{
    const calibration={points:calibrationPoints??[],tinHeightM:tin};
    if(!validWallCalibration(calibration)){setError("Those corners do not form a valid front wall. Clear them and mark the four landmarks in order.");return;}
    try{await persist((query.data?.shots??[]).map(s=>s.wall?.image?{...s,wall:{...s.wall,position:projectWall(calibration,s.wall.image)}}:s),calibration);setCalibrationPoints(null);setError(null);setSaved(true);}catch(e){setError(e instanceof Error?e.message:"Could not save calibration.");}
  };
  const exportReview=()=>{if(!query.data)return;const content={...query.data,matchId,scoreMethod:"placement-rubric-v2",ratings:shots.map(s=>({id:s.id,...gradeShot(s,wallCalibration?.tinHeightM)}))};const url=URL.createObjectURL(new Blob([JSON.stringify(content,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download=`squashvision-shot-review-r${reportRevision}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  const dots:VideoDot[]=[];
  const displayed=draft??selected;
  if(displayed){if(displayed.contactImage&&Math.abs(currentTimeUs-displayed.contactUs)<250_000)dots.push({point:displayed.contactImage,label:"Racket contact"});for(const [label,impact] of [["Front wall",displayed.wall],["First landing",displayed.landing]] as const)if(impact?.image&&Math.abs(currentTimeUs-impact.timeUs)<250_000)dots.push({point:impact.image,label});}
  if(!displayed)for(const c of timeline?.contacts??[]){const point=imagePoint(c);if(point&&c.proxyTimestampUs!==null&&Math.abs(currentTimeUs-c.proxyTimestampUs)<250_000)dots.push({point,label:c.kind.replaceAll("_"," ")});}
  if(calibrationPoints)calibrationPoints.forEach((point,i)=>dots.push({point,label:String(i+1)}));
  const picking=marking!==null||(calibrationPoints!==null&&calibrationPoints.length<4);
  const prompt=calibrationPoints!==null?wallSteps[calibrationPoints.length]??"Four wall landmarks marked":`Click the ball at ${marking==="contact"?"racket contact":marking==="wall"?"front-wall impact":"its first floor bounce"}`;

  return <section className="shot-lab" aria-labelledby="shot-lab-title">
    {videoHost&&createPortal(<ShotVideoOverlay active={picking} prompt={prompt} dots={dots} onPick={pick} onCancel={()=>{setMarking(null);setCalibrationPoints(null);}} width={videoRef.current?.videoWidth||1280} height={videoRef.current?.videoHeight||720}/>,videoHost)}
    <header className="shot-lab-header"><div><h2 id="shot-lab-title">Shot review</h2></div><div className="shot-lab-actions"><button type="button" disabled={!query.data||save.isPending||!!calibrationPoints} className="shot-primary" aria-label="Add shot at current frame" onClick={begin}>+ Mark a shot <span>{formatMatchTime(currentTimeUs,true)}</span></button><button disabled={!query.data||!!draft||save.isPending} onClick={()=>{videoRef.current?.pause();setEditVersion(query.data?.version??0);setCalibrationPoints([]);setError(null);videoHost?.scrollIntoView({behavior:"smooth",block:"center"});}}>Calibrate front wall</button><button disabled={!query.data||!!draft} onClick={exportReview}>Export shot review</button></div></header>
    {query.isPending?<p role="status">Loading saved shot review…</p>:query.isError?<div className="shot-error" role="alert">Could not load saved shots. <button onClick={()=>void query.refetch()}>Retry shot review</button></div>:null}
    {restored&&draft&&<p className="shot-saved" role="status">Unsaved draft restored for report {reportRevision}.</p>}
    {saved&&!draft&&<p className="shot-saved" role="status">Saved locally</p>}
    {calibrationPoints!==null&&<div className="shot-calibration"><strong>{calibrationPoints.length<4?prompt:"Wall landmarks ready"}</strong><p>Use a fixed camera view. Mark floor corners and the service-line ends on the front wall. The service line is 1.78 m above the floor.</p><label>Tin height<select value={tin} onChange={e=>setTin(Number(e.target.value))}><option value={.48}>Standard · 48 cm</option><option value={.43}>Professional · 43 cm</option></select></label><button onClick={()=>setCalibrationPoints([])}>Clear landmarks</button><button disabled={calibrationPoints.length!==4||save.isPending} onClick={()=>void saveCalibration()}>Save wall calibration</button><button onClick={()=>setCalibrationPoints(null)}>Cancel calibration</button></div>}
    {error&&!draft&&<p className="shot-error" role="alert">{error}</p>}
    {error?.includes("another tab")&&<button onClick={()=>void query.refetch().then(result=>{if(result.data)setEditVersion(result.data.version);})}>Reload saved review</button>}
    <div className="shot-lab-grid"><aside className="shot-list"><div className="shot-list-head"><strong>{shots.length} shot{shots.length===1?"":"s"}</strong><select aria-label="Filter shots by player" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">Both players</option><option value="A">Player A</option><option value="B">Player B</option></select></div>
      <div className="shot-list-items">{shown.map(s=>{const g=gradeShot(s,wallCalibration?.tinHeightM);const n=shots.indexOf(s)+1;return <button key={s.id} className={selected?.id===s.id?"is-selected":""} data-player={s.hitter??"unknown"} disabled={save.isPending} aria-label={`Shot ${n} · ${title(s)} · ${formatMatchTime(s.contactUs,true)}`} onClick={()=>choose(s)}><span className="shot-list-number">{String(n).padStart(2,"0")}</span><span><strong>{title(s)}</strong><small>{s.hitter?`Player ${s.hitter}`:"Player unknown"} · {formatMatchTime(s.contactUs,true)}</small></span><span className="shot-list-score">{rating(g.quality)}<small>/10</small></span></button>;})}</div>
      {!shots.length&&<div className="shot-empty"><strong>No shots available</strong><p>Pause the video and mark a contact to add a shot.</p></div>}
      <p className="shot-list-note">Automatic candidates in the loaded window, plus your saved reviews.</p>
      {!!timeline?.contacts.length&&<details className="shot-moments"><summary>Detected impact moments</summary>{timeline.contacts.map(c=><button key={c.id} onClick={()=>c.proxyTimestampUs!==null&&seek(c.proxyTimestampUs)} disabled={c.proxyTimestampUs===null}>{c.kind.replaceAll("_"," ")} <span>{formatMatchTime(c.proxyTimestampUs??c.timestampUs,true)}</span></button>)}<p>Unassigned moments are not complete shots.</p></details>}
    </aside><div className="shot-detail">
      {draft?<ShotEditor key={draft.id} shot={draft} onChange={setDraft} onMark={startMark} onSave={()=>void saveShot()} onCancel={cancelDraft} saving={save.isPending} error={error} durationUs={durationUs}/>:selected&&grade?<>
        <header className="shot-detail-header"><div><span className="shot-eyebrow">{selected.origin==="reviewed"?"Reviewed":"Tracked"}</span><h3>{title(selected)} <span>{selected.hitter?`Player ${selected.hitter}`:"Unassigned"}</span></h3></div><button onClick={()=>{setEditVersion(query.data?.version??0);setDraft(structuredClone(selected));setSaved(false);setError(null);}}>Edit shot</button></header>
        <div className="shot-scores"><div><span>Placement quality</span><strong>{rating(grade.quality)}<small>/10</small></strong><p>{grade.basis==="wall"?"Wall only · partial score":grade.partial?"Placement estimate":"Placement score"}</p></div><div><span>Retrieval difficulty</span><strong>{rating(grade.difficulty)}<small>/10</small></strong><p>{grade.difficulty===null?"Needs opponent evidence":"Higher = more travel pressure"}</p></div><div><span>Outgoing ball speed</span><strong>{speed?.value===null||speed?.value===undefined?"—":speed.value.toFixed(1)}<small>m/s</small></strong><p>{speed?.value!==null&&speed?.value!==undefined?`${Math.round(speed.coverage*100)}% of outgoing flight tracked · 2D estimate`:"Needs 3 tracked flight samples"}</p></div></div>
        <div className="shot-factors">{grade.factors.map(f=><div key={f.label}><label>{f.label}<span>{f.measurement}</span></label><meter min="0" max="10" value={f.score} aria-label={`${f.label} ${f.score} out of 10`}/></div>)}</div>
        <div className="shot-explanation"><strong>Why this score</strong><p>{grade.reasons.join(" ")}</p><p>{grade.difficultyReason}</p></div>
        <ShotDiagrams shot={selected} onSeek={seek} tinHeightM={wallCalibration?.tinHeightM}/>{selected.notes&&<p className="shot-notes">{selected.notes}</p>}
      </>:<div className="shot-detail-welcome"><h3>Select a shot</h3><p>Review its contact, wall impact and first bounce.</p><ol><li><b>1</b> Pause at racket contact</li><li><b>2</b> Mark the ball’s impacts</li><li><b>3</b> Review the score and replay</li></ol></div>}
    </div></div>
    <section className="shot-coaching"><div><h3>Placement summary</h3><p>{coaching.ratedCount?`${coaching.bounceRatedCount} bounce-based scores${coaching.average===null?"":` · ${coaching.average.toFixed(1)}/10 average`}${coaching.wallOnlyCount?` · ${coaching.wallOnlyCount} separate wall-only estimates`:""}` : "Review a few shots to reveal recurring placement patterns."}</p></div><div>{coaching.insights.map(s=><p key={s}>{s}</p>)}{coaching.weakest.length>0&&<div className="shot-replay-list"><strong>Shots to revisit</strong>{coaching.weakest.map(({shot,grade:g})=><button key={shot.id} onClick={()=>choose(shot)}>{title(shot)} · {formatMatchTime(shot.contactUs,true)} <b>{rating(g.quality)}/10</b></button>)}</div>}</div></section>
    <details className="shot-method"><summary>How the estimates work</summary><p>Placement rubric v2: drives reward tightness and first-bounce depth around 7.5 m; drops and boasts reward a short, tight bounce and low wall impact when calibrated; lobs reward depth and height. When a bounce is not visible, a partial score uses calibrated wall placement: side-wall tightness for drives, a central target for crosscourts, low impact for boasts/drops and clearance for lobs. This app-defined rubric scores placement. A wall-only score is partial; judging dying length or shot success also requires the later trajectory and rally outcome.</p><p>Difficulty uses the opponent’s travel pressure to the first landing. Reach, anticipation, volleys and second-bounce position remain outside this estimate. Speed is apparent 2D image motion, smoothed within continuous evidence and reset at detected impacts. Missing observations remain unavailable. A/B identities and automatic contact candidates need review.</p><p>Shot-review JSON contains your markers, calibration and rating explanations. Published analysis reports keep their original data.</p></details>
  </section>;
}
