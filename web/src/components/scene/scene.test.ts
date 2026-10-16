import { describe, expect, it } from "vitest";
import { LEVELS } from "./geometry";
import { muddiness, water } from "./water";

describe("scene", () => {
  it("takes its heights from the category thresholds", () => {
    expect(LEVELS).toMatchObject({
      park: 145,
      wall: 165,
      barrierTop: 185,
      bagTop: 225,
      floor: 225,
    });
  });

  it("turns the water brown across 225 cm and draws none when the river is dry", () => {
    expect(muddiness(219)).toBe(0);
    expect(muddiness(225)).toBe(0.5);
    expect(muddiness(231)).toBe(1);
    expect(water(0, false)).toBe("");
    expect(water(232, true)).not.toContain("sc-mud");
  });
});
