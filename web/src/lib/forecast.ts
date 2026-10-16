// Pure forecast logic for the page: categories, freshness, verdict, hover values. No DOM, no clock.
import { type Category, categories, freshness } from "./config";
import type {
  Band,
  ForecastPoint,
  ForecastResponse,
  HistoryPoint,
} from "./types";

const MINUTE_MS = 60_000;
const HOUR_MS = 3_600_000;

export type State = "fresh" | "stale" | "fallback" | "error";

/** The highest category whose threshold the level is strictly above: 145,0 cm is still category 1. */
export function categoryFor(levelCm: number): Category {
  return (
    categories.findLast(
      (category) => category.above_cm === null || levelCm > category.above_cm,
    ) ?? categories[0]
  );
}

/** Stale when either timestamp is older than its limit; fallback when the model step failed. */
export function stateOf(
  forecast: ForecastResponse | null,
  nowMs: number,
): State {
  if (forecast === null) return "error";
  const ageMinutes = (iso: string) => (nowMs - Date.parse(iso)) / MINUTE_MS;
  if (
    // Negated so an unparsable timestamp (NaN) counts as stale.
    !(
      ageMinutes(forecast.newest_observation_at) <=
        freshness.observation_max_age_minutes &&
      ageMinutes(forecast.issued_at) <= freshness.forecast_max_age_minutes
    )
  ) {
    return "stale";
  }
  const hasBands = forecast.points.some((point) => point.bands.length > 0);
  return forecast.model === "persistence" || !hasBands ? "fallback" : "fresh";
}

export function bandOf(
  point: ForecastPoint,
  coverage: 80 | 90,
): Band | undefined {
  return point.bands.find((band) => band.coverage_percent === coverage);
}

const upper90 = (point: ForecastPoint) =>
  bandOf(point, 90)?.upper_cm ?? point.level_cm;

// Time of the last point before `levelOf` goes above the threshold; the newest reading when the
// first point is already above. Null when it never does.
function crossingMs(
  forecast: ForecastResponse,
  thresholdCm: number,
  levelOf: (point: ForecastPoint) => number,
): number | null {
  const index = forecast.points.findIndex(
    (point) => levelOf(point) > thresholdCm,
  );
  if (index < 0) return null;
  if (index === 0) return Date.parse(forecast.newest_observation_at);
  return Date.parse(forecast.points[index - 1].valid_at);
}

export interface Crossing {
  category: Category;
  atMs: number;
}

export interface Verdict {
  expected: Category;
  expectedAt: Crossing | null;
  possible: Crossing | null;
}

/**
 * The forecast line sets the expected category; `expectedAt` is set only when that is above the
 * latest level's category, at the last point before the crossing (the newest reading when the
 * first point is already above). `possible` is the highest category above the expected one that
 * the 90 % top reaches.
 */
export function verdict(
  forecast: ForecastResponse,
  latestLevelCm: number,
  _nowMs: number,
): Verdict {
  const expected = categoryFor(
    Math.max(...forecast.points.map((point) => point.level_cm)),
  );
  const atMs =
    expected.above_cm !== null &&
    expected.number > categoryFor(latestLevelCm).number
      ? crossingMs(forecast, expected.above_cm, (point) => point.level_cm)
      : null;
  const expectedAt = atMs === null ? null : { category: expected, atMs };
  const possible =
    categories
      .filter(
        (category) =>
          category.number > expected.number && category.above_cm !== null,
      )
      .map((category) => ({
        category,
        atMs: crossingMs(forecast, category.above_cm ?? 0, upper90),
      }))
      .filter((crossing): crossing is Crossing => crossing.atMs !== null)
      .at(-1) ?? null;
  return { expected, expectedAt, possible };
}

export interface CategoryTag {
  current: boolean;
  expectedAtMs: number | null;
  /** Only when the line doesn't reach the category but the 90 % top does. */
  possibleFromMs: number | null;
  /** The level is above the threshold now or may get there; false for every card unless fresh. */
  reached: boolean;
}

/** One tag per category number, for the "Stufen und Maßnahmen" cards. */
export function categoryTags(
  forecast: ForecastResponse | null,
  latestLevelCm: number,
  state: State,
): Map<number, CategoryTag> {
  const currentNumber = categoryFor(latestLevelCm).number;
  const usable = state === "fresh" ? forecast : null;
  return new Map(
    categories.map((category) => {
      const threshold = category.above_cm;
      const passed = threshold !== null && latestLevelCm > threshold;
      const ahead = usable !== null && threshold !== null && !passed;
      const expectedAtMs = ahead
        ? crossingMs(usable, threshold, (point) => point.level_cm)
        : null;
      const possibleFromMs =
        ahead && expectedAtMs === null
          ? crossingMs(usable, threshold, upper90)
          : null;
      const reached =
        usable !== null &&
        threshold !== null &&
        (passed || expectedAtMs !== null || possibleFromMs !== null);
      return [
        category.number,
        {
          current: category.number === currentNumber,
          expectedAtMs,
          possibleFromMs,
          reached,
        },
      ];
    }),
  );
}

export interface LevelAt {
  levelCm: number;
  band90: [number, number] | null;
  measured: boolean;
}

interface Sample extends LevelAt {
  ms: number;
}

const lerp = (from: number, to: number, fraction: number) =>
  from + (to - from) * fraction;

/** The level at any time, linear between hours (also across gaps), clamped to the ends. */
export function levelAt(
  history: HistoryPoint[],
  points: ForecastPoint[] | null,
  timeMs: number,
): LevelAt | null {
  const samples: Sample[] = history.map((observation) => ({
    ms: Date.parse(observation.observed_at),
    levelCm: observation.level_cm,
    band90: null,
    measured: true,
  }));
  const newest = samples.at(-1);
  if (points !== null) {
    // The ranges open from the newest reading, as in the chart.
    if (newest) newest.band90 = [newest.levelCm, newest.levelCm];
    for (const point of points) {
      const band = bandOf(point, 90);
      samples.push({
        ms: Date.parse(point.valid_at),
        levelCm: point.level_cm,
        band90: band ? [band.lower_cm, band.upper_cm] : null,
        measured: false,
      });
    }
  }
  if (samples.length === 0) return null;

  const strip = ({ levelCm, band90, measured }: Sample): LevelAt => ({
    levelCm,
    band90,
    measured,
  });
  const afterIndex = samples.findIndex((sample) => timeMs <= sample.ms);
  if (afterIndex === 0) return strip(samples[0]);
  if (afterIndex < 0) return strip(samples[samples.length - 1]);
  const before = samples[afterIndex - 1];
  const after = samples[afterIndex];
  if (timeMs === after.ms) return strip(after);
  const fraction = (timeMs - before.ms) / (after.ms - before.ms);
  const nearer = fraction < 0.5 ? before : after;
  const band90: [number, number] | null =
    before.band90 && after.band90
      ? [
          lerp(before.band90[0], after.band90[0], fraction),
          lerp(before.band90[1], after.band90[1], fraction),
        ]
      : before.measured // two readings: no band between them
        ? null
        : nearer.band90;
  return {
    levelCm: lerp(before.levelCm, after.levelCm, fraction),
    band90,
    measured: before.measured && after.measured,
  };
}

/** Change of the measured level over the last 3 hours; null when history doesn't reach back that far. */
export function trend3h(history: HistoryPoint[]): number | null {
  const latest = history.at(-1);
  if (!latest) return null;
  const startMs = Date.parse(latest.observed_at) - 3 * HOUR_MS;
  if (Date.parse(history[0].observed_at) > startMs) return null;
  const start = levelAt(history, null, startMs);
  return start ? latest.level_cm - start.levelCm : null;
}

/** Centimetres left to the first flood threshold (145 cm); negative when above it. */
export function distanceToCritical(levelCm: number): number {
  return (categories[1].above_cm ?? 0) - levelCm;
}
