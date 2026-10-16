// The chart's background (category zones with threshold labels, the hour grid) and its pure geometry.
import { categories } from "../lib/config";

export const MARGIN = { l: 8, r: 50, t: 10, b: 26 };
const HOUR = 3600e3;

export interface Sample {
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

interface ChartGridProps {
  W: number;
  H: number;
  x: (ms: number) => number;
  y: (cm: number) => number;
  yMax: number;
  t0: number;
  t1: number;
  /** Narrow: a label every 12 hours instead of 6. */
  phone: boolean;
  /** False when stale: grey zones. */
  colored: boolean;
}

export default function ChartGrid({
  W,
  H,
  x,
  y,
  yMax,
  t0,
  t1,
  phone,
  colored,
}: ChartGridProps) {
  const ticks: { ms: number; hour: number; weekday: string }[] = [];
  for (let ms = Math.ceil(t0 / HOUR) * HOUR; ms <= t1; ms += HOUR) {
    const tick = berlinTick(ms);
    if (tick.hour % (phone ? 12 : 6) === 0) ticks.push({ ms, ...tick });
  }
  return (
    <>
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
          {x(tick.ms) >= MARGIN.l + 18 && x(tick.ms) <= W - MARGIN.r - 18 && (
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
    </>
  );
}
