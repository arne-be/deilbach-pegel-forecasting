// Measured level of the last day and the forecast with its 80/90 % ranges, over the category zones.
// Pointing at it (mouse, a sideways finger move, arrow keys) picks an hour and reports it via onHover.
import { type PointerEvent, useCallback, useMemo, useState } from "react";
import { historyHours, horizonHours, scaleTopCm } from "../lib/config";
import { bandOf, levelAt, type State } from "../lib/forecast";
import { berlinHourPhrase, formatCm } from "../lib/format";
import type { ForecastPoint, HistoryPoint } from "../lib/types";
import "./ForecastChart.css";
import ChartGrid, { linePath, MARGIN, scaleTop } from "./ChartGrid";
import { useChartCursor, useCursorGlide } from "./useChartCursor";

export interface ForecastChartProps {
  history: HistoryPoint[];
  /** Null unless `state` is "fresh". */
  points: ForecastPoint[] | null;
  /** From `stateOf`; "stale" greys the chart and marks "jetzt". */
  state: State;
  nowMs: number;
  onHover: (timeMs: number | null) => void;
  /** Hour picked on mount (screenshots with `&hover=`). */
  initialHoverMs?: number | null;
}

const HOUR = 3600e3;
const MAX_GAP_MS = 2 * HOUR;

export default function ForecastChart({
  history,
  points,
  state,
  nowMs,
  onHover,
  initialHoverMs = null,
}: ForecastChartProps) {
  const [width, setWidth] = useState(360);

  // A callback ref, so the observer attaches whenever the box mounts (e.g. once data arrives).
  const observeWidth = useCallback((box: HTMLDivElement | null) => {
    if (!box) return;
    const observer = new ResizeObserver(() => {
      if (box.clientWidth) setWidth(Math.round(box.clientWidth));
    });
    observer.observe(box);
    return () => observer.disconnect();
  }, []);

  const lastObservation = history.at(-1);
  const newestMs = lastObservation
    ? Date.parse(lastObservation.observed_at)
    : nowMs;
  const stale = state === "stale";
  const recent = useMemo(
    () =>
      history.filter(
        (o) => Date.parse(o.observed_at) >= newestMs - historyHours * HOUR - 1,
      ),
    [history, newestMs],
  );
  const measured = useMemo(
    () =>
      recent.map((o) => ({ ms: Date.parse(o.observed_at), cm: o.level_cm })),
    [recent],
  );
  const forecast = useMemo(
    () =>
      (points ?? []).map((p) => ({
        ms: Date.parse(p.valid_at),
        cm: p.level_cm,
      })),
    [points],
  );
  const series = useMemo(
    () => [...measured, ...forecast],
    [measured, forecast],
  );

  const phone = width < 500;
  const W = width;
  const H = phone ? 260 : 320;
  const yMax = scaleTop(
    [
      ...series.map((s) => s.cm),
      ...(points ?? []).map((p) => bandOf(p, 90)?.upper_cm ?? p.level_cm),
    ],
    scaleTopCm,
  );
  const t0 = newestMs - historyHours * HOUR;
  const t1 = newestMs + horizonHours * HOUR + 10 * 60e3;
  const { x, y } = useMemo(
    () => ({
      x: (ms: number) =>
        MARGIN.l + ((ms - t0) / (t1 - t0)) * (W - MARGIN.l - MARGIN.r),
      y: (cm: number) => MARGIN.t + (1 - cm / yMax) * (H - MARGIN.t - MARGIN.b),
    }),
    [t0, t1, W, H, yMax],
  );
  const homeIdx = measured.length - 1;
  const { shownIdx, handlers } = useChartCursor({
    series,
    homeIdx,
    timeAt: (event: PointerEvent<HTMLDivElement>) => {
      const rect = event.currentTarget.getBoundingClientRect();
      const px = ((event.clientX - rect.left) * W) / rect.width;
      return t0 + ((px - MARGIN.l) / (W - MARGIN.l - MARGIN.r)) * (t1 - t0);
    },
    onHover,
    initialHoverMs,
  });
  const away = shownIdx !== homeIdx;

  const cmAt = useCallback(
    (ms: number) => levelAt(recent, points, ms)?.levelCm,
    [recent, points],
  );
  const { lineRef, dotRef } = useCursorGlide(series[shownIdx], cmAt, x, y);

  if (!lastObservation || !measured.length) return null;

  const colored = !stale;
  const lineColor = stale ? "var(--muted-foreground)" : "var(--foreground)";
  const newest = measured[homeIdx];
  // The ranges open from the newest reading.
  const band = (coverage: 80 | 90) => {
    const edges = (points ?? []).flatMap((p) => {
      const b = bandOf(p, coverage);
      return b
        ? [{ ms: Date.parse(p.valid_at), lower: b.lower_cm, upper: b.upper_cm }]
        : [];
    });
    if (!edges.length) return null;
    const start = `${x(newest.ms)},${y(newest.cm)}`;
    const upper = edges.map((e) => `${x(e.ms)},${y(e.upper)}`);
    const lower = edges.map((e) => `${x(e.ms)},${y(e.lower)}`).reverse();
    return (
      <polygon
        points={[start, ...upper, ...lower].join(" ")}
        fill={`var(--band${coverage})`}
      />
    );
  };
  const shown = series[shownIdx];

  return (
    <div className="card fc">
      <div
        ref={observeWidth}
        className="fc-chart"
        role="slider"
        tabIndex={0}
        aria-label="Pegelverlauf: Stunde wählen, das Wasser am Haus folgt"
        aria-valuemin={0}
        aria-valuemax={series.length - 1}
        aria-valuenow={shownIdx}
        aria-valuetext={`${berlinHourPhrase(shown.ms, nowMs)} · ${formatCm(shown.cm)}${shownIdx > homeIdx ? " (Prognose)" : ""}`}
        {...handlers}
      >
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
          <ChartGrid
            W={W}
            H={H}
            x={x}
            y={y}
            yMax={yMax}
            t0={t0}
            t1={t1}
            phone={phone}
            colored={colored}
          />
          {band(90)}
          {band(80)}
          <path
            d={linePath(measured, x, y, MAX_GAP_MS)}
            fill="none"
            stroke={lineColor}
            strokeWidth={2.2}
            strokeLinejoin="round"
          />
          {forecast.length > 0 && (
            <path
              d={linePath([newest, ...forecast], x, y)}
              fill="none"
              stroke="var(--foreground)"
              strokeWidth={2.6}
              strokeDasharray="6 4"
            />
          )}
          <line
            x1={x(newest.ms)}
            x2={x(newest.ms)}
            y1={MARGIN.t}
            y2={H - MARGIN.b}
            stroke="var(--foreground)"
          />
          {stale && nowMs < t1 && (
            <>
              <line
                x1={x(nowMs)}
                x2={x(nowMs)}
                y1={MARGIN.t}
                y2={H - MARGIN.b}
                stroke="var(--destructive)"
                strokeWidth={2}
                strokeDasharray="4 3"
              />
              <text className="late" x={x(nowMs) + 4} y={H - MARGIN.b - 6}>
                jetzt
              </text>
            </>
          )}
          <circle
            cx={x(newest.ms)}
            cy={y(newest.cm)}
            r={3.5}
            fill={lineColor}
          />
          {!stale && (
            <text
              className="strong halo"
              x={x(newest.ms) + 9}
              y={y(newest.cm) + 20}
            >
              Jetzt
            </text>
          )}
          {series.length > 1 && (
            <text
              className="cue halo"
              x={x(newest.ms)}
              y={y(newest.cm) - 13}
              textAnchor="middle"
              opacity={away ? 0 : 1}
            >
              ↔
            </text>
          )}
          {/* The dot marks the shown hour (the newest reading at rest); the line appears while pointing. */}
          <g pointerEvents="none">
            <line
              ref={lineRef}
              className="cursor"
              x1={x(newest.ms)}
              x2={x(newest.ms)}
              y1={MARGIN.t}
              y2={H - MARGIN.b}
              opacity={away ? 1 : 0}
            />
            <circle
              ref={dotRef}
              cx={x(newest.ms)}
              cy={y(newest.cm)}
              r={6}
              fill="var(--card)"
              stroke={lineColor}
              strokeWidth={2.5}
            />
          </g>
        </svg>
      </div>
      <div className="fc-legend">
        <span>
          <span className="sw measured" />
          gemessen
        </span>
        {forecast.length > 0 && (
          <>
            <span>
              <span className="sw dashed" />
              Prognose
            </span>
            <span>
              <span className="sw band80" />
              wahrscheinlich
            </span>
            <span>
              <span className="sw band90" />
              möglich
            </span>
          </>
        )}
      </div>
    </div>
  );
}
