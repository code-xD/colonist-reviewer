"use client";

import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { AnalyzerReview, parseAnalyzer, ReviewMoment, VisualSnapshot } from "./replay";

const formatTime = (seconds?: number) => {
  if (seconds === undefined) return "—";
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
};

const safeColor = (color: string) => {
  const allowed = ["red", "blue", "orange", "green", "black", "white", "purple", "pink"];
  return allowed.includes(color.toLowerCase()) ? color.toLowerCase() : "white";
};

const resourceClass = (resource: string) => {
  const value = resource.toLowerCase();
  if (value.includes("wood") || value.includes("lumber")) return "wood";
  if (value.includes("brick")) return "brick";
  if (value.includes("sheep") || value.includes("wool")) return "wool";
  if (value.includes("wheat") || value.includes("grain")) return "grain";
  if (value.includes("ore")) return "ore";
  return "desert";
};

const boardTopology = (() => {
  const rowLengths = [3, 4, 5, 4, 3];
  const rawCenters = rowLengths.flatMap((length, row) => Array.from({ length }, (_, column) => ({ x: (Math.abs(2 - row) * .5 + column) * Math.sqrt(3), y: row * 1.5 })));
  const rawCorners: { x: number; y: number }[] = [];
  const cornerIds = new Map<string, number>();
  const rawEdges = new Set<string>();
  for (const center of rawCenters) {
    const tileCorners = Array.from({ length: 6 }, (_, index) => {
      const angle = ((60 * index - 30) * Math.PI) / 180;
      const point = { x: Number((center.x + Math.cos(angle)).toFixed(4)), y: Number((center.y + Math.sin(angle)).toFixed(4)) };
      const key = `${point.x.toFixed(4)}:${point.y.toFixed(4)}`;
      if (!cornerIds.has(key)) {
        cornerIds.set(key, rawCorners.length);
        rawCorners.push(point);
      }
      return cornerIds.get(key)!;
    });
    for (let index = 0; index < 6; index += 1) {
      rawEdges.add([tileCorners[index], tileCorners[(index + 1) % 6]].sort((a, b) => a - b).join(":"));
    }
  }
  const corners = rawCorners.map((point, rawIndex) => ({ ...point, rawIndex })).sort((a, b) => a.y - b.y || a.x - b.x);
  const remap = new Map(corners.map((corner, index) => [corner.rawIndex, index]));
  const edges = [...rawEdges].map((value) => value.split(":").map(Number)).map(([start, end]) => [remap.get(start)!, remap.get(end)!] as const).sort((a, b) => {
    const midpointA = { x: (corners[a[0]].x + corners[a[1]].x) / 2, y: (corners[a[0]].y + corners[a[1]].y) / 2 };
    const midpointB = { x: (corners[b[0]].x + corners[b[1]].x) / 2, y: (corners[b[0]].y + corners[b[1]].y) / 2 };
    return midpointA.y - midpointB.y || midpointA.x - midpointB.x;
  });
  const project = (point: { x: number; y: number }) => ({ x: 380 + (point.x - 2 * Math.sqrt(3)) * 58, y: 260 + (point.y - 3) * 58 });
  return { centers: rawCenters.map(project), corners: corners.map(project), edges };
})();

function VisualBoard({ snapshot }: { snapshot: VisualSnapshot }) {
  return (
    <svg className="board" viewBox="0 0 760 520" role="img" aria-label={`Board evidence at ${formatTime(snapshot.timestamp_seconds)}`}>
      <defs><filter id="tile-shadow"><feDropShadow dx="0" dy="5" stdDeviation="5" floodOpacity=".25" /></filter></defs>
      <g filter="url(#tile-shadow)">
        {snapshot.tiles.map((tile, index) => {
          const center = boardTopology.centers[tile.tile_index];
          if (!center) return null;
          const { x, y } = center;
          const points = Array.from({ length: 6 }, (_, point) => {
            const angle = ((60 * point - 30) * Math.PI) / 180;
            return `${x + 58 * Math.cos(angle)},${y + 58 * Math.sin(angle)}`;
          }).join(" ");
          return <g key={`${tile.tile_index}:${index}`}><polygon className={`tile tile-${resourceClass(tile.resource)}`} points={points} />{tile.dice_number ? <g><circle className="number-chip" cx={x} cy={y} r="15" /><text className={tile.dice_number === 6 || tile.dice_number === 8 ? "hot-number" : "tile-number"} x={x} y={y + 5}>{tile.dice_number}</text></g> : null}</g>;
        })}
      </g>
      {snapshot.roads.map((road, index) => {
        const edge = boardTopology.edges[road.edge_index];
        if (!edge) return null;
        const start = boardTopology.corners[edge[0]];
        const end = boardTopology.corners[edge[1]];
        return <line key={index} className={`road player-${safeColor(road.color)}`} x1={start.x} y1={start.y} x2={end.x} y2={end.y} />;
      })}
      {snapshot.buildings.map((building, index) => {
        const point = boardTopology.corners[building.corner_index];
        if (!point) return null;
        const { x, y } = point;
        return building.kind === "city"
          ? <path key={index} className={`building player-${safeColor(building.color)}`} d={`M${x - 10} ${y + 8}v-16l7-7 7 7v5h8v19z`} />
          : <path key={index} className={`building player-${safeColor(building.color)}`} d={`M${x - 9} ${y + 8}v-12l9-8 9 8v12z`} />;
      })}
      {snapshot.robber_tile_index !== null && boardTopology.centers[snapshot.robber_tile_index] ? <g className="robber" transform={`translate(${boardTopology.centers[snapshot.robber_tile_index].x - 8} ${boardTopology.centers[snapshot.robber_tile_index].y - 21})`}><circle cx="8" cy="7" r="7" /><path d="M3 14h10l4 22H-1z" /></g> : null}
    </svg>
  );
}

function EmptyBoard({ loaded }: { loaded: boolean }) {
  return <div className="empty-board"><span>{loaded ? "Report v1.0" : "Analyzer JSON"}</span><h2>{loaded ? "No board coordinates in this report" : "Load a completed review"}</h2><p>{loaded ? "The timeline and coaching below are accurate to this report. Re-run the updated analyzer to add visual board snapshots." : "Choose the JSON produced by the WebM analyzer. The file stays in this tab."}</p></div>;
}

function Coach({ moment }: { moment?: ReviewMoment }) {
  return <aside className="coach-panel panel"><div className="coach-header"><div><span className="eyebrow">Coach</span><h1>Decision review</h1></div>{moment ? <span className={`rating ${(moment.rating ?? "review").toLowerCase().replace(/\s+/g, "-")}`}>{moment.rating || "Review"}</span> : null}</div>{moment ? <><div className="moment-time">{formatTime(moment.time)}</div><h2>{moment.title}</h2><p className="analysis">{moment.detail || "This moment was identified from visible evidence in the recording."}</p><div className="comparison played"><span>Observed</span><strong>{moment.detail || moment.title}</strong></div><div className="comparison consider"><span>Consider</span><strong>{moment.suggestion || "No specific alternative was supported strongly enough by the sampled frames."}</strong></div></> : <div className="coach-empty"><h2>Post-game, not live</h2><p>Load a review to inspect each observed action and the closest supported alternative.</p></div>}<div className="privacy-note"><span>Local review</span><p>Your report stays in this browser tab.</p></div></aside>;
}

export default function Home() {
  const [review, setReview] = useState<AnalyzerReview>();
  const [index, setIndex] = useState(0);
  const [notice, setNotice] = useState("Waiting for an analyzer report.");
  const moments = review?.moments ?? [];
  const safeIndex = Math.min(index, Math.max(0, moments.length - 1));
  const moment = moments[safeIndex];
  const snapshot = useMemo(() => {
    if (!review?.snapshots.length || !moment) return undefined;
    return review.snapshots.reduce((nearest, candidate) => Math.abs(candidate.timestamp_seconds - (moment.time ?? 0)) < Math.abs(nearest.timestamp_seconds - (moment.time ?? 0)) ? candidate : nearest);
  }, [moment, review]);

  const applyReport = (data: unknown, name: string) => {
    const parsed = parseAnalyzer(data);
    setReview(parsed);
    setIndex(0);
    setNotice(`${parsed.moments.length} review moments and ${parsed.snapshots.length} board snapshots loaded from ${name}.`);
  };

  const loadJson = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      applyReport(JSON.parse(await file.text()), file.name);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "The selected report could not be read.");
    }
    event.target.value = "";
  };

  useEffect(() => {
    const report = new URLSearchParams(window.location.search).get("report");
    if (!report?.startsWith("/")) return;
    fetch(report)
      .then((response) => {
        if (!response.ok) throw new Error(`Could not load ${report}.`);
        return response.json();
      })
      .then((data) => applyReport(data, report.split("/").at(-1) || report))
      .catch((error: unknown) => setNotice(error instanceof Error ? error.message : `Could not load ${report}.`));
  }, []);

  useEffect(() => {
    const move = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft") setIndex((value) => Math.max(0, value - 1));
      if (event.key === "ArrowRight") setIndex((value) => Math.min(moments.length - 1, value + 1));
    };
    window.addEventListener("keydown", move);
    return () => window.removeEventListener("keydown", move);
  }, [moments.length]);

  return <main><header className="topbar"><div className="brand"><span className="brand-mark">S</span><div><strong>Settlement Review</strong><span>Post-game decision lab</span></div></div><label className="upload primary">Open analyzer JSON<input type="file" accept="application/json,.json" onChange={loadJson} /></label></header><section className="status-strip"><span className="status-dot" />{notice}</section><div className="workspace"><aside className="left-panel panel"><div className="panel-heading"><span>{review?.reviewedPlayer || "No player"}</span><strong>{moments.length ? `${safeIndex + 1} / ${moments.length}` : "—"}</strong></div><div className="review-player"><span className="player-dot player-blue" /><div><strong>{review?.reviewedPlayer || "Load a report"}</strong><span>{review ? "Reviewed player" : "WebM analyzer output"}</span></div></div><div className="log-section"><div className="eyebrow">Timeline</div><ol className="move-log">{moments.slice(Math.max(0, safeIndex - 2), safeIndex + 3).map((item) => <li className={item === moment ? "selected" : ""} key={`${item.time}:${item.title}`}><span>{formatTime(item.time)}</span>{item.title}</li>)}</ol></div></aside><section className="board-panel"><div className="turn-banner"><strong>{snapshot?.active_player || review?.reviewedPlayer || "Replay evidence"}</strong><span>{formatTime(moment?.time)}</span></div><div className="ocean">{snapshot ? <VisualBoard snapshot={snapshot} /> : <EmptyBoard loaded={Boolean(review)} />}</div><div className="playback"><button onClick={() => setIndex(0)} disabled={!moments.length || safeIndex === 0}>↤</button><button onClick={() => setIndex((value) => Math.max(0, value - 1))} disabled={!moments.length || safeIndex === 0}>←</button><input aria-label="Review position" type="range" min="0" max={Math.max(0, moments.length - 1)} value={safeIndex} disabled={!moments.length} onChange={(event) => setIndex(Number(event.target.value))} /><span>{moments.length ? `${safeIndex + 1} / ${moments.length}` : "0 / 0"}</span><button onClick={() => setIndex((value) => Math.min(moments.length - 1, value + 1))} disabled={!moments.length || safeIndex === moments.length - 1}>→</button><button onClick={() => setIndex(moments.length - 1)} disabled={!moments.length || safeIndex === moments.length - 1}>↦</button></div></section><Coach moment={moment} /></div></main>;
}
