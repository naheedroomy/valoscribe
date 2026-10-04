import { AlertTriangle, Check, Circle, FileVideo2, Play, ShieldCheck } from "lucide-react";
import type { RoundStatus } from "@/lib/types";

export interface StudioInput { vodPath: string; mapName: string; matchId: string; mapId: string; fromRound: number; toRound: number; team: string; profilePath: string; manifestPath: string; outputDir: string; verifySha: boolean }
type Manifest = { path: string; data: { rounds: Array<{map_round:number; status:RoundStatus;round_id:string}>; teams: Record<string,{name:string;starting_side:string}>; match_id:string;map_id:string;map_name:string } };
type Profile = {path:string;data:{profile_id:string;calibration_status:string}};
type Vod = {path:string;name:string;size:number};
const sizeLabel = (bytes:number) => bytes >= 1e9 ? `${(bytes/1e9).toFixed(2)} GB` : `${(bytes/1e6).toFixed(0)} MB`;
const compactLabel = (value:string) => value.length > 34 ? `${value.slice(0,15)}…${value.slice(-12)}` : value;
const statusWord = (status:RoundStatus) => status === "confirmed" ? "confirmed" : status === "excluded" ? "excluded" : status === "missing" ? "missing" : "unresolved";

export function PreflightConfig({ manifests, profiles, vods, input, setInput, onPreflight, busy, error }: { manifests:Manifest[];profiles:Profile[];vods:Vod[];input:StudioInput;setInput:(next:StudioInput)=>void;onPreflight:()=>void;busy:boolean;error:string }) {
  const manifest = manifests.find((item)=>item.path===input.manifestPath);
  const rounds = manifest?.data.rounds ?? [];
  const chosenVod=vods.find((vod)=>vod.path===input.vodPath);
  function preset(path:string) {
    const selected=manifests.find((item)=>item.path===path); if(!selected)return;
    const first=selected.data.rounds.filter((round)=>round.status==="confirmed").map((round)=>round.map_round);
    const start=first[0]??1;let end=start;while(first.includes(end+1))end++;
    const team=Object.keys(selected.data.teams)[0] ?? "";
    setInput({...input,manifestPath:selected.path,matchId:selected.data.match_id,mapId:selected.data.map_id,mapName:selected.data.map_name,fromRound:start,toRound:end,team});
  }
  return <section className="config-panel" aria-labelledby="config-title">
    <div className="section-head"><div><span className="section-index">CONFIGURE</span><h2 id="config-title">Source &amp; rounds</h2></div><span className="offline-tag">LOCAL FILES</span></div>
    <label className="field-label" htmlFor="manifest">Round manifest</label>
    <select id="manifest" value={input.manifestPath} onChange={(event)=>preset(event.target.value)} disabled={!manifests.length}>
      {manifests.map((item)=><option key={item.path} value={item.path}>{compactLabel(item.data.match_id)} · {item.data.map_name}</option>)}
    </select>
    {!manifests.length && <p className="hint">No local manifest found. Add a JSON round manifest under configs/examples.</p>}
    <label className="field-label" htmlFor="vod">Broadcast VOD</label>
    <select id="vod" value={input.vodPath} onChange={(event)=>setInput({...input,vodPath:event.target.value})} disabled={!vods.length}>
      {vods.map((vod)=><option key={vod.path} value={vod.path}>{compactLabel(vod.name)}</option>)}
    </select>
    <div className="file-meta"><FileVideo2 size={14}/><span>{chosenVod ? chosenVod.name : "No approved source file detected"}</span><b>{chosenVod ? sizeLabel(chosenVod.size) : "—"}</b></div>
    <div className="form-row"><label><span className="field-label">From round</span><input type="number" min={1} max={99} value={input.fromRound} onChange={(e)=>setInput({...input,fromRound:Number(e.target.value)})}/></label><label><span className="field-label">To round</span><input type="number" min={input.fromRound} max={99} value={input.toRound} onChange={(e)=>setInput({...input,toRound:Number(e.target.value)})}/></label><label><span className="field-label">Team</span><select value={input.team} onChange={(e)=>setInput({...input,team:e.target.value})}>{Object.entries(manifest?.data.teams??{}).map(([id,team])=><option key={id} value={id}>{team.name} ({id})</option>)}</select></label></div>
    <div className="side-note"><span>STARTING SIDES · MANIFEST</span>{Object.entries(manifest?.data.teams??{}).map(([id,team])=><b key={id}>{id}<i>{team.starting_side}</i></b>)}</div>
    <div className="matrix-title"><span>ROUND STATUS</span><span>R{input.fromRound}—R{input.toRound}</span></div>
    <div className="round-matrix" role="group" aria-label="Round manifest status">
      {Array.from({length:15},(_,index)=>index+1).map((number)=>{const found=rounds.find((round)=>round.map_round===number);const state=found?.status??"missing";return <button key={number} type="button" className={`round-cell ${state} ${number>=input.fromRound&&number<=input.toRound?"selected":""}`} title={`Round ${number}: ${statusWord(state)}`} aria-label={`Round ${number}, ${statusWord(state)}`} aria-pressed={number>=input.fromRound&&number<=input.toRound} onClick={()=>setInput({...input,fromRound:number,toRound:number})}><span>{number}</span>{state==="confirmed"?<Check size={11}/>:state==="missing"?<Circle size={9}/>:<AlertTriangle size={11}/>}</button>})}
    </div>
    <p className="hint"><span className="key-dot green"/> confirmed <span className="key-dot amber"/> unresolved <span className="key-dot grey"/> absent / excluded</p>
    <label className="checkline"><input type="checkbox" checked={input.verifySha} onChange={(e)=>setInput({...input,verifySha:e.target.checked})}/><span>Verify source SHA-256 before run</span><ShieldCheck size={14}/></label>
    <label className="field-label" htmlFor="profile">Broadcast profile</label><select id="profile" value={input.profilePath} onChange={(e)=>setInput({...input,profilePath:e.target.value})}>{profiles.map((profile)=><option key={profile.path} value={profile.path}>{compactLabel(profile.data.profile_id)} · {profile.data.calibration_status}</option>)}</select>
    <button className="primary-button" onClick={onPreflight} disabled={busy||!input.vodPath||!input.manifestPath||!input.profilePath}><Play size={15} fill="currentColor"/>{busy?"INSPECTING SOURCE…":"RUN PREFLIGHT INSPECTION"}</button>
    {error&&<div className="inline-error" role="alert"><AlertTriangle size={15}/><span>{error}</span></div>}
  </section>;
}
