import { describe, expect, it } from "vitest";
import { fixtures } from "../fixtures";
import {
  categoryFor,
  categoryTags,
  distanceToCritical,
  levelAt,
  stateOf,
  trend3h,
  verdict,
} from "./forecast";
import { berlinHourPhrase, formatCm } from "./format";
import type { ForecastResponse } from "./types";

const MINUTE_MS = 60_000;
const HOUR_MS = 3_600_000;
const flood = fixtures.flood;
const floodNow = Date.parse(flood.now);
const floodNewestMs = Date.parse(flood.forecast.newest_observation_at);

describe("categoryFor", () => {
  it("is strictly above the threshold", () => {
    expect(categoryFor(145).number).toBe(1);
    expect(categoryFor(145.1).number).toBe(2);
    expect(categoryFor(0).number).toBe(1);
    expect(categoryFor(230).number).toBe(5);
  });
});

describe("stateOf", () => {
  const fresh = fixtures.normal.forecast;
  const newestMs = Date.parse(fresh.newest_observation_at);
  const issuedMs = Date.parse(fresh.issued_at);

  it("reads the fixtures", () => {
    expect(stateOf(fresh, Date.parse(fixtures.normal.now))).toBe("fresh");
    expect(stateOf(flood.forecast, floodNow)).toBe("fresh");
    expect(
      stateOf(fixtures.stale.forecast, Date.parse(fixtures.stale.now)),
    ).toBe("stale");
    expect(
      stateOf(fixtures.fallback.forecast, Date.parse(fixtures.fallback.now)),
    ).toBe("fallback");
    expect(stateOf(null, floodNow)).toBe("error");
    expect(stateOf({ ...flood.forecast, issued_at: "" }, floodNow)).toBe(
      "stale",
    );
  });

  it("allows 90 minutes on the newest observation", () => {
    const recentIssue = {
      ...fresh,
      issued_at: new Date(newestMs + 90 * MINUTE_MS).toISOString(),
    };
    expect(stateOf(recentIssue, newestMs + 90 * MINUTE_MS)).toBe("fresh");
    expect(stateOf(recentIssue, newestMs + 90 * MINUTE_MS + 1)).toBe("stale");
  });

  it("allows 90 minutes on the issue time", () => {
    const recentReading = {
      ...fresh,
      newest_observation_at: new Date(issuedMs + 90 * MINUTE_MS).toISOString(),
    };
    expect(stateOf(recentReading, issuedMs + 90 * MINUTE_MS)).toBe("fresh");
    expect(stateOf(recentReading, issuedMs + 90 * MINUTE_MS + 1)).toBe("stale");
  });

  it("falls back by model name or when no point has bands", () => {
    const now = Date.parse(fixtures.normal.now);
    expect(stateOf({ ...fresh, model: "persistence" }, now)).toBe("fallback");
    const noBands = {
      ...fresh,
      points: fresh.points.map((point) => ({ ...point, bands: [] })),
    };
    expect(stateOf(noBands, now)).toBe("fallback");
    // Empty bands past the model's last lead are fine.
    const lastLeadBare = {
      ...fresh,
      points: fresh.points.map((point, index) =>
        index === 23 ? { ...point, bands: [] } : point,
      ),
    };
    expect(stateOf(lastLeadBare, now)).toBe("fresh");
  });
});

describe("verdict", () => {
  it("names category 3 expected and category 4 possible in the flood", () => {
    const result = verdict(flood.forecast, 128, floodNow);
    expect(result.expected.number).toBe(3);
    expect(result.expectedAt?.category.number).toBe(3);
    expect(berlinHourPhrase(result.expectedAt?.atMs ?? 0, floodNow)).toBe(
      "heute 21 Uhr",
    );
    expect(result.possible?.category.number).toBe(4);
    expect(berlinHourPhrase(result.possible?.atMs ?? 0, floodNow)).toBe(
      "heute 21 Uhr",
    );
  });

  it("stays at category 1 with nothing possible on a normal day", () => {
    const result = verdict(
      fixtures.normal.forecast,
      18.9,
      Date.parse(fixtures.normal.now),
    );
    expect(result.expected.number).toBe(1);
    expect(result.expectedAt).toBeNull();
    expect(result.possible).toBeNull();
  });

  it("expects category 5 in chaos with nothing above", () => {
    const chaos = fixtures.chaos;
    const result = verdict(chaos.forecast, 188, Date.parse(chaos.now));
    expect(result.expected.number).toBe(5);
    expect(
      berlinHourPhrase(result.expectedAt?.atMs ?? 0, Date.parse(chaos.now)),
    ).toBe("heute 21 Uhr");
    expect(result.possible).toBeNull();
  });

  it("has no time when the latest level is in the expected category already", () => {
    const high: ForecastResponse = {
      ...flood.forecast,
      points: flood.forecast.points.map((point) => ({
        ...point,
        level_cm: 150,
        bands: [],
      })),
    };
    const result = verdict(high, 146, floodNow);
    expect(result.expected.number).toBe(2);
    expect(result.expectedAt).toBeNull();
  });

  it("dates a crossing before the first point at the newest reading", () => {
    const high: ForecastResponse = {
      ...flood.forecast,
      points: flood.forecast.points.map((point) => ({
        ...point,
        level_cm: 150,
      })),
    };
    const result = verdict(high, 140, floodNow);
    expect(result.expectedAt?.category.number).toBe(2);
    expect(berlinHourPhrase(result.expectedAt?.atMs ?? 0, floodNow)).toBe(
      "heute 16 Uhr",
    );
  });
});

describe("categoryTags", () => {
  it("tags only the current category on a normal day", () => {
    const tags = categoryTags(fixtures.normal.forecast, 18.9, "fresh");
    expect(tags.get(1)).toEqual({
      current: true,
      expectedAtMs: null,
      possibleFromMs: null,
      reached: false,
    });
    for (const number of [2, 3, 4, 5])
      expect(tags.get(number)?.reached).toBe(false);
  });

  it("tags expected and possible categories in the flood", () => {
    const tags = categoryTags(flood.forecast, 128, "fresh");
    expect(tags.get(1)?.current).toBe(true);
    expect(berlinHourPhrase(tags.get(2)?.expectedAtMs ?? 0, floodNow)).toBe(
      "heute 18 Uhr",
    );
    expect(berlinHourPhrase(tags.get(3)?.expectedAtMs ?? 0, floodNow)).toBe(
      "heute 21 Uhr",
    );
    expect(tags.get(4)).toMatchObject({ expectedAtMs: null, reached: true });
    expect(berlinHourPhrase(tags.get(4)?.possibleFromMs ?? 0, floodNow)).toBe(
      "heute 21 Uhr",
    );
    expect(tags.get(5)).toEqual({
      current: false,
      expectedAtMs: null,
      possibleFromMs: null,
      reached: false,
    });
  });

  it("drops every forecast tag when stale", () => {
    const tags = categoryTags(fixtures.stale.forecast, 128, "stale");
    expect(tags.get(1)?.current).toBe(true);
    for (const tag of tags.values()) {
      expect(tag).toMatchObject({
        expectedAtMs: null,
        possibleFromMs: null,
        reached: false,
      });
    }
  });

  it("marks passed thresholds reached in chaos", () => {
    const chaos = fixtures.chaos;
    const tags = categoryTags(chaos.forecast, 188, "fresh");
    expect(tags.get(1)?.reached).toBe(false);
    expect(tags.get(2)).toMatchObject({ reached: true, expectedAtMs: null });
    expect(tags.get(3)).toMatchObject({ reached: true, expectedAtMs: null });
    expect(tags.get(4)).toMatchObject({
      current: true,
      reached: true,
      expectedAtMs: null,
    });
    expect(
      berlinHourPhrase(tags.get(5)?.expectedAtMs ?? 0, Date.parse(chaos.now)),
    ).toBe("heute 21 Uhr");
  });
});

describe("levelAt", () => {
  const history = flood.history.observations;
  const points = flood.forecast.points;

  it("reads the flood numbers the mockup shows", () => {
    expect(
      formatCm(
        levelAt(history, points, floodNewestMs + 3 * HOUR_MS)?.levelCm ?? 0,
      ),
    ).toBe("146 cm");
    const peak = points.reduce((top, point) =>
      point.level_cm > top.level_cm ? point : top,
    );
    expect(peak.level_cm).toBe(172);
    expect(berlinHourPhrase(Date.parse(peak.valid_at), floodNow)).toBe(
      "heute 23 Uhr",
    );
  });

  it("interpolates between measured hours", () => {
    const result = levelAt(history, points, floodNewestMs - 30 * MINUTE_MS);
    expect(result?.levelCm).toBeCloseTo(125);
    expect(result?.measured).toBe(true);
    expect(result?.band90).toBeNull();
  });

  it("interpolates between forecast hours with the 90 % band", () => {
    const halfPast = Date.parse(points[1].valid_at) + 30 * MINUTE_MS;
    const result = levelAt(history, points, halfPast);
    expect(result?.levelCm).toBeCloseTo((138.7 + 145.8) / 2);
    expect(result?.measured).toBe(false);
    expect(result?.band90?.[0]).toBeCloseTo((127.8 + 132.0) / 2);
    expect(result?.band90?.[1]).toBeCloseTo((149.6 + 159.6) / 2);
  });

  it("widens the band from the newest reading to the first forecast hour", () => {
    const halfway = (floodNewestMs + Date.parse(points[0].valid_at)) / 2;
    const result = levelAt(history, points, halfway);
    expect(result?.measured).toBe(false);
    expect(result?.levelCm).toBeCloseTo((128 + 133.7) / 2);
    expect(result?.band90?.[0]).toBeCloseTo((128 + 125.6) / 2);
    expect(result?.band90?.[1]).toBeCloseTo((128 + 141.8) / 2);
  });

  it("opens the band from the newest reading", () => {
    expect(levelAt(history, points, floodNewestMs)).toEqual({
      levelCm: 128,
      band90: [128, 128],
      measured: true,
    });
    expect(levelAt(history, null, floodNewestMs)?.band90).toBeNull();
  });

  it("bridges a missing hour and clamps at the ends", () => {
    const normal = fixtures.normal.history.observations;
    // 2026-10-15 15:22 is missing: 19.2 cm before, 18.3 cm after.
    expect(
      normal.some((o) => o.observed_at.startsWith("2026-10-15T15:22")),
    ).toBe(false);
    expect(
      levelAt(normal, null, Date.parse("2026-10-15T15:22:03Z"))?.levelCm,
    ).toBeCloseTo(18.75);
    expect(levelAt(normal, null, 0)?.levelCm).toBe(normal[0].level_cm);
    expect(levelAt([], null, 0)).toBeNull();
  });
});

describe("trend3h", () => {
  it("measures the change over three hours by time", () => {
    expect(trend3h(flood.history.observations)).toBeCloseTo(128 - 116.9);
  });

  it("is null without three hours of history", () => {
    expect(trend3h(flood.history.observations.slice(-3))).toBeNull();
    expect(trend3h([])).toBeNull();
  });
});

describe("distanceToCritical", () => {
  it("counts down to 145 cm", () => {
    expect(distanceToCritical(128)).toBe(17);
    expect(distanceToCritical(150)).toBe(-5);
  });
});
