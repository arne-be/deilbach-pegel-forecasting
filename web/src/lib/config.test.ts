import { describe, expect, it } from "vitest";
import { fixtures } from "../fixtures";
import {
  categories,
  freshness,
  historyHours,
  scaleTopCm,
  support,
  supportReady,
} from "./config";

describe("config", () => {
  it("reads categories with ascending bounds below the scale top", () => {
    expect(categories.map((category) => category.number)).toEqual([
      1, 2, 3, 4, 5,
    ]);
    expect(categories[0]?.above_cm).toBeNull();
    const bounds = categories
      .slice(1)
      .map((category) => category.above_cm ?? Number.NaN);
    expect(bounds).toEqual([...bounds].sort((a, b) => a - b));
    expect(Math.max(...bounds)).toBeLessThan(scaleTopCm);
    expect(categories.every((category) => category.actions)).toBe(true);
  });

  it("reads freshness and site settings", () => {
    expect(freshness.observation_max_age_minutes).toBe(90);
    expect(historyHours).toBe(24);
  });

  it("reads the support offer with every link set", () => {
    expect(support.tiers.map((tier) => tier.id)).toEqual([
      "zentimeter",
      "dezimeter",
      "meter",
    ]);
    expect(supportReady).toBe(true);
  });
});

describe("fixtures", () => {
  it("are what the plan says", () => {
    const last = (name: keyof typeof fixtures) =>
      fixtures[name].history.observations.at(-1)?.level_cm;
    expect(last("chaos")).toBe(188);
    expect(fixtures.fallback.forecast.model).toBe("persistence");
    expect(
      fixtures.fallback.forecast.points.every(
        (point) => point.bands.length === 0,
      ),
    ).toBe(true);
    expect(fixtures.normal.forecast.points).toHaveLength(24);
  });
});
