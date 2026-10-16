// Test data. `normal` is real (prod, 2026-10-16, without the 95 % band); the others are made up
// on top of a flood shaped like the 19.11.2024 record. `now` is the time each case is viewed at.
import type { ForecastResponse, HistoryResponse } from "../lib/types";
import chaos from "./chaos.json";
import fallback from "./fallback.json";
import flood from "./flood.json";
import normal from "./normal.json";

export interface Fixture {
  now: string;
  forecast: ForecastResponse;
  history: HistoryResponse;
}

export const fixtures = {
  normal: { now: "2026-10-16T09:41:00Z", ...normal },
  flood: { now: "2026-11-19T15:41:00Z", ...flood },
  // The flood, viewed two hours later: both timestamps older than 90 minutes.
  stale: { now: "2026-11-19T17:40:00Z", ...flood },
  // A persistence forecast (flat at the last level, no bands), as when the model step fails.
  fallback: { now: "2026-11-19T15:41:00Z", ...fallback },
  // The flood 60 cm higher: 188 cm now (Kat. 4), peak 232 cm (Kat. 5).
  chaos: { now: "2026-11-19T15:41:00Z", ...chaos },
} satisfies Record<string, Fixture>;

export type FixtureName = keyof typeof fixtures;
