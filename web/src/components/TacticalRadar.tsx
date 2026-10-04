import { useMemo, useState } from "react";
import { ascentZones } from "@/lib/ascent-zones";
import type { CorrectedObservation } from "@/lib/types";

function inside(point: CorrectedObservation, vertices: [number, number][]) {
  let hit = false;
  for (let i = 0, j = vertices.length - 1; i < vertices.length; j = i++) {
    const [xi, yi] = vertices[i]; const [xj, yj] = vertices[j];
    if (((yi > point.canonical_y) !== (yj > point.canonical_y)) && point.canonical_x < (xj - xi) * (point.canonical_y - yi) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

export function TacticalRadar({ observations, timestamp }: { observations: CorrectedObservation[]; timestamp: number }) {
  const [active, setActive] = useState<string | null>(null);
  const frame = useMemo(() => {
    const bySample = new Map<number, CorrectedObservation[]>();
    for (const marker of observations) {
      const list = bySample.get(marker.sample_index) ?? [];
      list.push(marker); bySample.set(marker.sample_index, list);
    }
    const nearest = [...bySample.values()].sort((a, b) => Math.abs(a[0].source_timestamp_seconds - timestamp) - Math.abs(b[0].source_timestamp_seconds - timestamp))[0];
    return nearest && Math.abs(nearest[0].source_timestamp_seconds - timestamp) < 0.75 ? nearest : [];
  }, [observations, timestamp]);
  const activeZone = ascentZones.find((zone) => zone.zone_id === active);
  const activeMarkers = activeZone ? frame.filter((marker) => inside(marker, activeZone.vertices_px)) : [];
  const averageConfidence = activeMarkers.length ? activeMarkers.reduce((sum, marker) => sum + marker.confidence, 0) / activeMarkers.length : null;
  return <section className="radar-panel" aria-labelledby="radar-title">
    <div className="section-head"><div><span className="section-index">CANONICAL SPACE · 2048²</span><h2 id="radar-title">Ascent / observation board</h2></div><span className="approx-tag">APPROX. GEOMETRY</span></div>
    <div className="radar-legend"><span><i className="legend-dot raw"/> detector candidate</span><span><i className="legend-dot corrected"/> source correction</span><span className="radar-frame">{frame.length} observed · {timestamp.toFixed(2)}s</span></div>
    <div className="radar-wrap"><svg viewBox="0 0 2048 2048" role="group" aria-label={`Ascent canonical map with ${frame.length} anonymous observations at ${timestamp.toFixed(2)} seconds`}>
      <image href="/ascent-canonical.png" x="0" y="0" width="2048" height="2048" preserveAspectRatio="none"/>
      <g className="zone-layer">{ascentZones.map((zone) => {
        const members = frame.filter((marker) => inside(marker, zone.vertices_px));
        const confidence = members.length ? members.reduce((sum, marker) => sum + marker.confidence, 0) / members.length : null;
        const center = zone.vertices_px.reduce(([x, y], [nextX, nextY]) => [x + nextX / zone.vertices_px.length, y + nextY / zone.vertices_px.length], [0, 0]);
        const label = `${zone.name}: ${members.length} anonymous observed marker${members.length === 1 ? "" : "s"}${confidence === null ? "; no observation confidence available" : `; mean confidence ${(confidence * 100).toFixed(0)} percent`}`;
        return <g key={zone.zone_id} role="button" tabIndex={0} aria-label={`${label}; focus or activate to inspect occupancy`} onMouseEnter={() => setActive(zone.zone_id)} onMouseLeave={() => setActive(null)} onFocus={() => setActive(zone.zone_id)} onBlur={() => setActive(null)} onClick={() => setActive(active === zone.zone_id ? null : zone.zone_id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setActive(active === zone.zone_id ? null : zone.zone_id); } }}>
          <polygon points={zone.vertices_px.map(([x, y]) => `${x},${y}`).join(" ")} className={active === zone.zone_id ? "zone active" : "zone"}/>
          {members.length > 0 && <g className="occupancy-badge" transform={`translate(${center[0]} ${center[1]})`} aria-hidden="true"><rect x="-33" y="-12" width="66" height="24" rx="3"/><text y="4" textAnchor="middle">{members.length} obs</text></g>}
        </g>;
      })}</g>
      <g>{frame.map((marker, index) => <g key={marker.observation_id ?? `${marker.sample_index}-${index}`} transform={`translate(${marker.canonical_x} ${marker.canonical_y})`} className={marker.corrected ? "marker corrected-marker" : "marker"}><circle r="13"/><circle className="marker-core" r="4"/><title>{marker.corrected ? "Source-corrected center" : "Anonymous marker candidate"} · confidence {(marker.confidence * 100).toFixed(0)}%{marker.quality_flags?.length ? ` · ${marker.quality_flags.join(", ")}` : ""}</title></g>)}</g>
    </svg></div>
    <div className="radar-footer"><span>{activeZone ? `${activeZone.name} · ${activeMarkers.length} observed markers · ${averageConfidence === null ? "confidence unavailable" : `mean confidence ${(averageConfidence * 100).toFixed(0)}%`}` : "Focus or hover a zone for observed occupancy and confidence"}</span><span>Unknown / excluded remain unassigned</span></div>
    <p className="radar-caveat">Approximate candidate zone boundaries; counts are anonymous observed centers, not players or full-team occupancy. Source corrections remain distinct from raw detections.</p>
  </section>;
}
