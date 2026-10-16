import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { fixtures } from "../fixtures";
import type { State } from "../lib/forecast";
import { linePath, scaleTop } from "./ChartGrid";
import ForecastChart from "./ForecastChart";
import { nearestIndex } from "./useChartCursor";

const HOUR = 3600e3;
const same = (value: number) => value;

describe("scaleTop", () => {
  it("keeps the configured top while every value fits", () => {
    expect(scaleTop([19, 172, 250], 250)).toBe(250);
  });
  it("grows in 25 cm steps above it", () => {
    expect(scaleTop([20, 251], 250)).toBe(275);
    expect(scaleTop([280], 250)).toBe(300);
  });
});

describe("linePath", () => {
  const at = (hour: number, cm: number) => ({ ms: hour * HOUR, cm });
  it("joins hourly readings across a single missing hour", () => {
    expect(linePath([at(0, 1), at(1, 2), at(3, 3)], same, same, 2 * HOUR)).toBe(
      `M0.0,1.0L${HOUR}.0,2.0L${3 * HOUR}.0,3.0`,
    );
  });
  it("lifts the pen across a gap longer than 2 h", () => {
    expect(linePath([at(0, 1), at(3, 2)], same, same, 2 * HOUR)).toBe(
      `M0.0,1.0M${3 * HOUR}.0,2.0`,
    );
  });
});

describe("nearestIndex", () => {
  it("picks the closest sample", () => {
    const samples = [0, 1, 2].map((hour) => ({ ms: hour * HOUR, cm: 0 }));
    expect(nearestIndex(samples, 1.4 * HOUR)).toBe(1);
    expect(nearestIndex(samples, 9 * HOUR)).toBe(2);
  });
});

describe("ForecastChart state", () => {
  const { forecast, history, now } = fixtures.flood;
  const render = (state: State) =>
    renderToStaticMarkup(
      <ForecastChart
        history={history.observations}
        points={state === "fresh" ? forecast.points : null}
        state={state}
        nowMs={Date.parse(now)}
        onHover={() => {}}
      />,
    );

  it("draws the forecast and its legend only when fresh", () => {
    expect(render("fresh")).toContain("Prognose");
    expect(render("fallback")).not.toContain("Prognose");
  });
  it("greys out and marks jetzt only when stale, whatever the clock says", () => {
    expect(render("stale")).toContain(">jetzt<");
    expect(render("stale")).not.toContain(">Jetzt<");
    expect(render("fallback")).toContain(">Jetzt<");
    expect(render("fresh")).not.toContain(">jetzt<");
  });
});
