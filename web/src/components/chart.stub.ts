// shortcut: stand-ins for forecast.ts and format.ts (package 2) with the agreed signatures;
// package 5 points the imports in ForecastChart.tsx at the real modules and deletes this file.
import type { Band, ForecastPoint, HistoryPoint } from "../lib/types";

export function bandOf(
  point: ForecastPoint,
  coverage: 80 | 90,
): Band | undefined {
  return point.bands.find((band) => band.coverage_percent === coverage);
}

export interface LevelAt {
  levelCm: number;
  band90: [number, number] | null;
  measured: boolean;
}

export function levelAt(
  history: HistoryPoint[],
  points: ForecastPoint[] | null,
  timeMs: number,
): LevelAt | null {
  const series = [
    ...history.map((o) => ({
      ms: Date.parse(o.observed_at),
      cm: o.level_cm,
      measured: true,
    })),
    ...(points ?? []).map((p) => ({
      ms: Date.parse(p.valid_at),
      cm: p.level_cm,
      measured: false,
    })),
  ];
  if (!series.length) return null;
  const after = series.findIndex((s) => s.ms >= timeMs);
  if (after <= 0) {
    const edge = after === 0 ? series[0] : series[series.length - 1];
    return { levelCm: edge.cm, band90: null, measured: edge.measured };
  }
  const a = series[after - 1];
  const b = series[after];
  const share = (timeMs - a.ms) / (b.ms - a.ms);
  return {
    levelCm: a.cm + (b.cm - a.cm) * share,
    band90: null,
    measured: b.measured,
  };
}

const parts = (ms: number) =>
  Object.fromEntries(
    new Intl.DateTimeFormat("de-DE", {
      timeZone: "Europe/Berlin",
      day: "2-digit",
      month: "2-digit",
      hour: "numeric",
      weekday: "short",
      hourCycle: "h23",
    })
      .formatToParts(new Date(ms))
      .map((part) => [part.type, part.value]),
  );

export function formatCm(levelCm: number, decimals: 0 | 1 = 0): string {
  return `${levelCm.toLocaleString("de-DE", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })} cm`;
}

export function berlinHourPhrase(ms: number, nowMs: number): string {
  const day = (t: number) => `${parts(t).day}.${parts(t).month}`;
  const word =
    day(ms) === day(nowMs)
      ? "heute"
      : day(ms) === day(nowMs + 864e5)
        ? "morgen"
        : parts(ms).weekday;
  return `${word} ${Number(parts(ms).hour)} Uhr`;
}
