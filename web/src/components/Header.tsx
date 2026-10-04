import { Copy, Radio, ShieldCheck } from "lucide-react";

export function Header({ sha, status, onCopy }: { sha?: string; status: string; onCopy: () => void }) {
  return <header className="topbar">
    <a className="brand" href="#workspace" aria-label="Valoscribe Studio home"><span className="brand-mark">V</span><span>VALOSCRIBE <small>TACTICAL STUDIO</small></span></a>
    <div className="matchline"><span className="live-dot"/><span>VCT AMERICAS · STAGE 2</span><b>GRAND FINAL</b><span className="map-chip">MAP 3 / ASCENT</span></div>
    <div className="top-status"><div className="teams"><b>100T</b><span>vs</span><b>LOUD</b></div><button className="sha-chip" onClick={onCopy} title="Copy source SHA-256"><span>SHA</span><code>{sha ? `${sha.slice(0, 10)}…${sha.slice(-6)}` : "NOT VERIFIED"}</code><Copy size={13}/></button><span className={`status-pill ${status === "passed" ? "good" : ""}`}><ShieldCheck size={13}/>{status === "passed" ? "PREFLIGHT PASSED" : "UNVERIFIED"}</span></div>
    <div className="mobile-title"><Radio size={14}/> AScent · Map 3 <span>LOCAL / OFFLINE</span></div>
  </header>;
}
