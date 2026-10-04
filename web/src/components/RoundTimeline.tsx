import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import type { ExcludedSpan } from "@/lib/types";

type CommitmentWindow = { start_timestamp_seconds?: number; end_timestamp_seconds?: number; confidence?: string };
type CommitmentWindows = { persistence_window?: CommitmentWindow | null; reversal_check_window?: CommitmentWindow | null } | null;
type TimelineBand = { left: string; width: string; visible: boolean };

export function RoundTimeline({roundNumber,start,end,live,excluded,time,playing,onSeek,onPlay,onStep,onRate,rate,commitment}:{roundNumber:number;start:number;end:number;live:number;excluded:ExcludedSpan[];time:number;playing:boolean;onSeek:(time:number)=>void;onPlay:()=>void;onStep:(delta:number)=>void;onRate:(rate:number)=>void;rate:number;commitment?:CommitmentWindows}) {
 const span=Math.max(0.1,end-start);
 const pct=(n:number)=>`${Math.max(0,Math.min(100,(n-start)/span*100))}%`;
 const band=(from:number,to:number):TimelineBand=>{
  const clippedStart=Math.max(start,Math.min(end,from));
  const clippedEnd=Math.max(start,Math.min(end,to));
  return {left:pct(clippedStart),width:`${Math.max(0,(clippedEnd-clippedStart)/span*100)}%`,visible:clippedEnd>clippedStart};
 };
 const freezeBand=band(start,live);
 const openingBand=band(live,live+8);
 const midBand=band(live+8,end);
 const persistenceBand=commitment?.persistence_window?.start_timestamp_seconds!==undefined&&commitment.persistence_window.end_timestamp_seconds!==undefined?band(commitment.persistence_window.start_timestamp_seconds,commitment.persistence_window.end_timestamp_seconds):null;
 const reversalBand=commitment?.reversal_check_window?.start_timestamp_seconds!==undefined&&commitment.reversal_check_window.end_timestamp_seconds!==undefined?band(commitment.reversal_check_window.start_timestamp_seconds,commitment.reversal_check_window.end_timestamp_seconds):null;
 const commitmentElement=(geometry:TimelineBand|null,window:CommitmentWindow|undefined,opacity:number,label:string)=>geometry?.visible&&window?<div className="phase" style={{left:geometry.left,width:geometry.width,background:"#d9973b",opacity}} title={`${label} · ${window.confidence??"partial evidence"}`}/>:null;
 const hasExcludedBand=excluded.some(item=>band(item.start_seconds,item.end_seconds).visible);
 return <section className="timeline-panel" aria-label="Round video timeline"><div className="timeline-top"><div className="play-controls"><button onClick={onPlay} aria-label={playing?"Pause video":"Play video"}>{playing?<Pause size={15}/>:<Play size={15}/>}</button><button onClick={()=>onStep(-.25)} aria-label="Step backward 0.25 seconds"><SkipBack size={14}/></button><button onClick={()=>onStep(.25)} aria-label="Step forward 0.25 seconds"><SkipForward size={14}/></button><select aria-label="Playback speed" value={rate} onChange={(event)=>onRate(Number(event.target.value))}>{[0.25,0.5,1,1.5,2].map(value=><option value={value} key={value}>{value}×</option>)}</select></div><output className="time-readout">{time.toFixed(2)} <span>/ {start.toFixed(0)}–{end.toFixed(0)} sec</span></output></div>
 <div className="phase-legend">{freezeBand.visible&&live>start&&<span><i style={{background:"#687384"}}/> Freeze time</span>}{openingBand.visible&&<span><i className="opening-band"/> Opening · 0–8s</span>}{midBand.visible&&<span><i className="mid-band"/> Mid-round</span>}<span><i className="site-band unknown-band"/> Site phase unknown</span>{(persistenceBand?.visible||reversalBand?.visible)&&<span><i style={{background:"#d9973b"}}/> Commitment candidate window · partial evidence</span>}{hasExcludedBand&&<span><i className="excluded-band"/> Excluded / replay</span>}</div>
 <div className="timeline-track-wrap"><div className="timeline-track" aria-hidden="true">{freezeBand.visible&&live>start&&<div className="phase" style={{left:freezeBand.left,width:freezeBand.width,background:"#687384"}} title="Freeze time from stored round interval"/>}{openingBand.visible&&<div className="phase opening" style={{left:openingBand.left,width:openingBand.width}}/>}{midBand.visible&&<div className="phase mid" style={{left:midBand.left,width:midBand.width}}/>}{commitmentElement(persistenceBand,commitment?.persistence_window??undefined,.8,"Stored candidate persistence window")}{commitmentElement(reversalBand,commitment?.reversal_check_window??undefined,.45,"Stored reversal-check window")}{excluded.map((item,index)=>{const geometry=band(item.start_seconds,item.end_seconds);return geometry.visible?<div className="phase excluded" key={index} style={{left:geometry.left,width:geometry.width}} title={item.reason}/>:null})}<div className="timeline-cursor" style={{left:pct(time)}}/></div><input aria-label="Seek within selected round" type="range" min={start} max={end} step="0.05" value={Math.max(start,Math.min(end,time))} onChange={(event)=>onSeek(Number(event.target.value))}/></div><div className="timeline-ends"><span>R{roundNumber} LIVE</span><span>{end.toFixed(0)}s · SOURCE TIME</span></div></section>;
}
