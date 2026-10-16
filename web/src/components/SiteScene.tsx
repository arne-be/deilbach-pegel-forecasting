// Isometric picture of the gauge site with the water at a level: car park, wall, barriers, sandbags, house.
import { useEffect, useRef } from "react";
import { SceneEngine } from "./scene/engine";
import { VB_WIDE } from "./scene/geometry";
import "./SiteScene.css";

export interface SiteSceneProps {
  levelCm: number;
  label: string; // e.g. "Fr. 23 Uhr · 172 cm"
  range: [number, number] | null; // 90 % band at a forecast hour
  stale: boolean; // grey, still water
}

export default function SiteScene({
  levelCm,
  label,
  range,
  stale,
}: SiteSceneProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const engineRef = useRef<SceneEngine | null>(null);

  useEffect(() => {
    if (!svgRef.current) return;
    const engine = new SceneEngine(svgRef.current);
    engineRef.current = engine;
    return () => {
      engine.destroy();
      engineRef.current = null;
    };
  }, []);

  useEffect(() => {
    engineRef.current?.setStale(stale);
  }, [stale]);

  // Compare the range by value, so a new array with the same bounds doesn't restart the easing.
  const [low, high] = range ?? [null, null];
  useEffect(() => {
    engineRef.current?.setLevel(
      levelCm,
      label,
      low === null || high === null ? null : [low, high],
    );
  }, [levelCm, label, low, high]);

  return (
    <div className="card site-scene">
      <svg
        ref={svgRef}
        className={stale ? "sc-scene sc-stale" : "sc-scene"}
        viewBox={VB_WIDE.join(" ")}
        role="img"
        aria-label="Schaubild Pegel Kupferdreh"
      >
        <defs>
          <linearGradient id="sc-wgrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" className="sc-wgrad-top" />
            <stop offset="1" className="sc-wgrad-bot" />
          </linearGradient>
          <filter id="sc-blur" x="-10%" y="-10%" width="120%" height="140%">
            <feGaussianBlur stdDeviation="9" />
          </filter>
          <filter id="sc-glow" x="-5%" y="-20%" width="110%" height="140%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="5" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <linearGradient id="sc-mgrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" className="sc-mgrad-top" />
            <stop offset="1" className="sc-mgrad-bot" />
          </linearGradient>
        </defs>
        {/* Drawn by SceneEngine: the static layer once per layout, the dynamic one on every level change. */}
        <g className="sc-static" />
        <g className="sc-dyn" />
      </svg>
    </div>
  );
}
