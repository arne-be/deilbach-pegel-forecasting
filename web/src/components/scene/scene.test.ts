import { describe, expect, it } from "vitest";
import { LEVELS, THRESHOLDS } from "./geometry";
import { muddiness, water } from "./water";

const [, cat3 = 0, cat4 = 0, cat5 = 0] = THRESHOLDS;

describe("scene", () => {
  it("takes its heights from the category thresholds", () => {
    expect(LEVELS).toMatchObject({
      park: cat3,
      wall: cat4,
      barriersUp: cat3,
      sandbags: cat3,
      barrierTop: cat5,
      bagTop: cat5,
      floor: cat5,
    });
  });

  it("turns the water brown across category 5 and draws none when the river is dry", () => {
    expect(muddiness(cat5 - 6)).toBe(0);
    expect(muddiness(cat5)).toBe(0.5);
    expect(muddiness(cat5 + 6)).toBe(1);
    expect(water(0, false)).toBe("");
    expect(water(cat5 + 7, true)).not.toContain("sc-mud");
  });
});
