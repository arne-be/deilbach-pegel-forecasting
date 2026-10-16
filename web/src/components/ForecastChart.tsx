// Measured level of the last day and the forecast with its 80/90 % ranges, over the category zones.
// Pointing at it (mouse, a sideways finger move, arrow keys) picks an hour and reports it via onHover.
import {
  type KeyboardEvent,
  type PointerEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  categories,
  historyHours,
  horizonHours,
  scaleTopCm,
} from "../lib/config";
import { bandOf, levelAt, type State } from "../lib/forecast";
import { berlinHourPhrase, formatCm } from "../lib/format";
import type { ForecastPoint, HistoryPoint } from "../lib/types";
import "./ForecastChart.css";

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
const HOLD_MS = 1500;
const MARGIN = { l: 8, r: 50, t: 10, b: 26 };

interface Sample {
  ms: number;
  cm: number;
}

/** The configured top, raised in 25 cm steps only when a value goes above it. */
export function scaleTop(valuesCm: number[], topCm: number): number {
  const highest = Math.max(...valuesCm);
  return highest > topCm ? Math.ceil((highest + 10) / 25) * 25 : topCm;
}

/** SVG path through the samples, lifted wherever two neighbours are more than `maxGapMs` apart. */
export function linePath(
  samples: Sample[],
  x: (ms: number) => number,
  y: (cm: number) => number,
  maxGapMs = Number.POSITIVE_INFINITY,
): string {
  return samples
    .map((s, i) => {
      const move = i === 0 || s.ms - samples[i - 1].ms > maxGapMs;
      return `${move ? "M" : "L"}${x(s.ms).toFixed(1)},${y(s.cm).toFixed(1)}`;
    })
    .join("");
}

export function nearestIndex(samples: Sample[], ms: number): number {
  let best = 0;
  samples.forEach((s, i) => {
    if (Math.abs(s.ms - ms) < Math.abs(samples[best].ms - ms)) best = i;
  });
  return best;
}

const hourParts = new Intl.DateTimeFormat("de-DE", {
  timeZone: "Europe/Berlin",
  day: "2-digit", // with a day in the format the weekday gets its dot: "Do."
  hour: "numeric",
  weekday: "short",
  hourCycle: "h23",
});
function berlinTick(ms: number): { hour: number; weekday: string } {
  const parts = Object.fromEntries(
    hourParts.formatToParts(new Date(ms)).map((p) => [p.type, p.value]),
  );
  return { hour: Number(parts.hour), weekday: parts.weekday };
}

const zoneColor = (number: number, colored: boolean) =>
  colored ? `var(--c${number})` : "var(--grey)";

export default function ForecastChart({
  history,
  points,
  state,
  nowMs,
  onHover,
  initialHoverMs = null,
}: ForecastChartProps) {
  const lineRef = useRef<SVGLineElement>(null);
  const dotRef = useRef<SVGCircleElement>(null);
  const shownMsRef = useRef<number | null>(null);
  const holdRef = useRef(0);
  const touchRef = useRef<{
    id: number;
    x: number;
    y: number;
    following: boolean;
  } | null>(null);
  const [width, setWidth] = useState(360);
  // The picked hour as a time, so a refresh that slides the window keeps the same hour.
  const [pickedMs, setPickedMs] = useState<number | null>(initialHoverMs);

  // A callback ref, so the observer attaches whenever the box mounts (e.g. once data arrives).
  const observeWidth = useCallback((box: HTMLDivElement | null) => {
    if (!box) return;
    const observer = new ResizeObserver(() => {
      if (box.clientWidth) setWidth(Math.round(box.clientWidth));
    });
    observer.observe(box);
    return () => observer.disconnect();
  }, []);
  useEffect(() => () => clearTimeout(holdRef.current), []);

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
  const shownIdx = pickedMs === null ? homeIdx : nearestIndex(series, pickedMs);
  const away = shownIdx !== homeIdx;

  // The cursor glides to the picked hour along the line; set on the DOM so a frame costs no render.
  useEffect(() => {
    const target = series[shownIdx];
    if (!target) return;
    const draw = (ms: number) => {
      const cm = levelAt(recent, points, ms)?.levelCm ?? target.cm;
      lineRef.current?.setAttribute("x1", String(x(ms)));
      lineRef.current?.setAttribute("x2", String(x(ms)));
      dotRef.current?.setAttribute("cx", String(x(ms)));
      dotRef.current?.setAttribute("cy", String(y(cm)));
    };
    const instant =
      matchMedia("(prefers-reduced-motion: reduce)").matches ||
      shownMsRef.current === null;
    if (instant) {
      shownMsRef.current = target.ms;
      draw(target.ms);
      return;
    }
    let raf = 0;
    let last = 0;
    const step = (ts: number) => {
      const dt = last ? Math.min(250, ts - last) : 16;
      last = ts;
      let shown = shownMsRef.current ?? target.ms;
      shown += (target.ms - shown) * (1 - Math.exp(-dt / 140));
      if (Math.abs(target.ms - shown) < 20e3) shown = target.ms;
      shownMsRef.current = shown;
      draw(shown);
      if (shown !== target.ms) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [series, recent, points, shownIdx, x, y]);

  if (!lastObservation || !measured.length) return null;

  const pick = (idx: number) => {
    clearTimeout(holdRef.current);
    const clamped = Math.max(0, Math.min(series.length - 1, idx));
    if (series[clamped].ms === pickedMs) return;
    setPickedMs(series[clamped].ms);
    onHover(series[clamped].ms);
  };
  const release = () => {
    // No early return on "nothing picked": the hold timer runs a release from an older render.
    clearTimeout(holdRef.current);
    setPickedMs(null);
    onHover(null);
  };
  const holdThenRelease = () => {
    clearTimeout(holdRef.current);
    holdRef.current = window.setTimeout(release, HOLD_MS);
  };
  const pickAt = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const px = ((event.clientX - rect.left) * W) / rect.width;
    pick(
      nearestIndex(
        series,
        t0 + ((px - MARGIN.l) / (W - MARGIN.l - MARGIN.r)) * (t1 - t0),
      ),
    );
  };

  // Mouse follows on hover. Touch follows from the first sideways move, so a vertical swipe scrolls
  // the page; a tap picks one hour. The picked hour holds 1.5 s after the finger lifts.
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "mouse") return;
    touchRef.current = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      following: false,
    };
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "mouse") return pickAt(event);
    const touch = touchRef.current;
    if (!touch || touch.id !== event.pointerId) return;
    if (!touch.following) {
      const dx = Math.abs(event.clientX - touch.x);
      const dy = Math.abs(event.clientY - touch.y);
      if (dy > 8 && dy > dx) {
        touchRef.current = null;
        return;
      }
      if (dx < 6) return;
      touch.following = true;
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    pickAt(event);
  };
  const onPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    const touch = touchRef.current;
    if (!touch || touch.id !== event.pointerId) return;
    if (!touch.following) pickAt(event);
    touchRef.current = null;
    holdThenRelease();
  };
  const onPointerCancel = () => {
    if (touchRef.current?.following) holdThenRelease();
    touchRef.current = null;
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const moves: Record<string, number> = {
      ArrowLeft: shownIdx - 1,
      ArrowRight: shownIdx + 1,
      Home: 0,
      End: series.length - 1,
    };
    if (event.key in moves) {
      event.preventDefault();
      pick(moves[event.key]);
    } else if (event.key === "Escape") release();
  };

  const colored = !stale;
  const lineColor = stale ? "var(--muted-foreground)" : "var(--foreground)";
  const newest = measured[homeIdx];
  const ticks: { ms: number; hour: number; weekday: string }[] = [];
  for (let ms = Math.ceil(t0 / HOUR) * HOUR; ms <= t1; ms += HOUR) {
    const tick = berlinTick(ms);
    if (tick.hour % (phone ? 12 : 6) === 0) ticks.push({ ms, ...tick });
  }
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
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onPointerLeave={(event) => event.pointerType === "mouse" && release()}
        onKeyDown={onKeyDown}
        onBlur={release}
      >
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
          {categories.map((category, i) => {
            const lo = Math.max(0, category.above_cm ?? 0);
            const hi = Math.min(yMax, categories[i + 1]?.above_cm ?? yMax);
            const firstZoneOpacity = category.number === 1 ? 0.12 : 0.22;
            return (
              <g key={category.number}>
                <rect
                  x={MARGIN.l}
                  y={y(hi)}
                  width={W - MARGIN.l - MARGIN.r}
                  height={y(lo) - y(hi)}
                  fill={zoneColor(category.number, colored)}
                  opacity={colored ? firstZoneOpacity : 0.2}
                />
                {category.above_cm !== null && (
                  <>
                    <line
                      x1={MARGIN.l}
                      x2={W - MARGIN.r}
                      y1={y(category.above_cm)}
                      y2={y(category.above_cm)}
                      stroke={zoneColor(category.number, colored)}
                      strokeWidth={1.5}
                    />
                    <text
                      className="strong"
                      x={W - MARGIN.r + 6}
                      y={y(category.above_cm) + 4}
                    >
                      {category.above_cm} · {category.number}
                    </text>
                  </>
                )}
              </g>
            );
          })}
          {ticks.map((tick) => (
            <g key={tick.ms}>
              <line
                x1={x(tick.ms)}
                x2={x(tick.ms)}
                y1={MARGIN.t}
                y2={H - MARGIN.b}
                stroke="var(--border)"
                strokeWidth={tick.hour === 0 ? 1.2 : 0.5}
              />
              {/* A label at the edge would be clipped. */}
              {x(tick.ms) >= MARGIN.l + 18 &&
                x(tick.ms) <= W - MARGIN.r - 18 && (
                  <text
                    x={x(tick.ms)}
                    y={H - 8}
                    textAnchor="middle"
                    fontWeight={tick.hour === 0 ? 700 : undefined}
                  >
                    {tick.hour === 0 ? tick.weekday : `${tick.hour} Uhr`}
                  </text>
                )}
            </g>
          ))}
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
