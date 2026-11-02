import {useMemo} from "react";
import type {PlaybackTimeline} from "./playback-model";
import {automaticShots,mergeShots} from "./shot-model";
import {gradeShot,shotLabel} from "./shot-quality";
import {useShotReview} from "./shot-review-data";
import {formatMatchTime} from "./analysis-model";
import "./LiveShotPanel.css";

interface Props {
  matchId:string;
  reportRevision:number;
  timeline:PlaybackTimeline|null;
  currentTimeUs:number;
  onSeek:(timeUs:number)=>void;
}
export function LiveShotPanel({matchId,reportRevision,timeline,currentTimeUs,onSeek}:Props) {
  const {query}=useShotReview(matchId,reportRevision);
  const shots=useMemo(()=>mergeShots(automaticShots(timeline,query.data?.wallCalibration),query.data?.shots??[]),[timeline,query.data?.shots,query.data?.wallCalibration]);
  const index=shots.findLastIndex(shot=>shot.contactUs<=currentTimeUs);
  const candidate=shots[index]??null;
  const observedEnd=candidate?.landing?.timeUs??candidate?.wall?.timeUs??candidate?.contactUs??0;
  const shot=candidate&&(timeline!==null||currentTimeUs<=observedEnd)?candidate:null;
  const grade=shot?gradeShot(shot,query.data?.wallCalibration?.tinHeightM):null;
  const quality=grade?.quality??null;
  const landing=shot?.landing?.position;
  const wallOnly=grade?.basis==="wall";
  const measured=wallOnly?shot?.wall?.position:landing;
  const tone=quality===null?"empty":quality>=7?"good":quality>=4?"fair":"weak";
  return <section className="live-shot" aria-label="Current shot" data-tone={tone}>
    <header><h2>Shot quality</h2><span className="live-shot-estimate" title={wallOnly?"Partial score from observed front-wall placement. No measured first bounce or final outcome.":"Estimated placement from tracked or video-reviewed markers. Not a validated professional rating."}>{wallOnly?"Wall only":"Estimated"}</span></header>
    <div className="live-shot-main">
      <div className="live-shot-score" data-testid="current-shot-quality"><strong>{quality===null?"—":quality.toFixed(1)}</strong><span>/ 10</span></div>
      <div className="live-shot-description"><h3 title={shot?.notes||undefined}>{shot?shotLabel(shot):candidate?"No shot data":"Ready to play"}</h3><p>{shot?`${shot.hitter?`Player ${shot.hitter} · `:""}${formatMatchTime(shot.contactUs,true)}`:candidate?"Select a tracked moment":"Select a shot or press play"}</p><span>{quality===null?(shot?"Placement unavailable":""):wallOnly?"Front-wall placement":quality>=8?"Excellent placement":quality>=6?"Good placement":quality>=4?"Room to improve":"Loose or short"}</span></div>
    </div>
    <div className="live-shot-scale" role="meter" aria-label="Estimated shot quality" aria-valuemin={0} aria-valuemax={10} {...(quality===null?{}:{"aria-valuenow":quality})}>{Array.from({length:10},(_,i)=><i key={i} data-filled={quality!==null&&i<Math.round(quality)}/>)}</div>
    <dl className="live-shot-placement">
      <div><dt>{wallOnly?"From wall corner":"From side wall"}</dt><dd>{measured?`${Math.round(Math.min(measured[0],6.4-measured[0])*100)} cm`:"—"}</dd></div>
      <div><dt>{wallOnly?"Wall height":"Bounce depth"}</dt><dd>{measured?`${measured[1].toFixed(2)} m`:"—"}</dd></div>
      <div><dt>Difficulty</dt><dd>{grade?.difficulty===null||grade?.difficulty===undefined?"—":`${grade.difficulty.toFixed(1)}/10`}</dd></div>
    </dl>
    <nav className="live-shot-navigation" aria-label="Shot navigation"><button type="button" aria-label="Previous shot" disabled={index<=0} onClick={()=>onSeek(shots[index-1].contactUs)}>←</button><span>{shots.length?`${Math.max(0,index+1)} / ${shots.length} shots`:"No shots available"}</span><button type="button" aria-label="Next shot" disabled={index+1>=shots.length} onClick={()=>onSeek(shots[index+1].contactUs)}>→</button></nav>
    {query.isError&&<button className="live-shot-retry" onClick={()=>void query.refetch()}>Reload saved shots</button>}
  </section>;
}
