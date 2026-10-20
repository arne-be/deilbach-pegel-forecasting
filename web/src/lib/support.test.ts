import { describe, expect, it } from "vitest";
import { fixtures } from "../fixtures";
import { support } from "./config";
import { categoryFor, verdict } from "./forecast";
import {
  firstVisit,
  parseMemory,
  parseThanks,
  peakCategory,
  recordVisit,
  type SupportMemory,
  shouldPrompt,
  withoutThanks,
} from "./support";

// 2026-10-20 in Berlin (CEST, UTC+2).
const morning = Date.parse("2026-10-20T06:00Z");
const lateEvening = Date.parse("2026-10-20T21:30Z"); // 23:30 in Berlin, same day
const afterMidnight = Date.parse("2026-10-20T22:30Z"); // 00:30 in Berlin, next day
const regular: SupportMemory = { ...firstVisit, visits: 5 };

describe("parseMemory", () => {
  it("reads what was stored", () => {
    const stored = { ...regular, lastVisitMs: morning, supported: true };
    expect(parseMemory(JSON.stringify(stored))).toEqual(stored);
  });

  it("treats nothing or junk as a first visit", () => {
    expect(parseMemory(null)).toEqual(firstVisit);
    expect(parseMemory("{")).toEqual(firstVisit);
    expect(parseMemory('{"visits":"5","supported":false}')).toEqual(firstVisit);
    expect(parseMemory("null")).toEqual(firstVisit);
  });
});

describe("recordVisit", () => {
  it("counts one visit per Berlin day", () => {
    const first = recordVisit(firstVisit, morning);
    expect(first.visits).toBe(1);
    expect(recordVisit(first, lateEvening)).toBe(first);
    expect(recordVisit(first, afterMidnight).visits).toBe(2);
  });
});

describe("peakCategory", () => {
  it("counts an expected flood even while the level is still low", () => {
    const { forecast, history, now } = fixtures.flood;
    const latest = history.observations.at(-1)?.level_cm ?? 0;
    const current = categoryFor(latest).number;
    const peak = peakCategory(
      current,
      verdict(forecast, latest, Date.parse(now)),
    );
    expect(current).toBeLessThanOrEqual(2);
    expect(peak).toBeGreaterThanOrEqual(3);
  });

  it("is the current category without a forecast", () => {
    expect(peakCategory(2, null)).toBe(2);
  });
});

describe("shouldPrompt", () => {
  const after = support.prompt_after_visits ?? 5;
  const ask = (memory: SupportMemory, state = "fresh", category = 1) =>
    shouldPrompt(memory, after, state as "fresh", category, morning);

  it("starts at the threshold", () => {
    expect(ask({ ...regular, visits: after - 1 })).toBe(false);
    expect(ask({ ...regular, visits: after })).toBe(true);
    expect(ask({ ...regular, visits: after + 7 })).toBe(true);
  });

  it("is off when the threshold is null", () => {
    expect(shouldPrompt(regular, null, "fresh", 1, morning)).toBe(false);
  });

  it("never asks supporters", () => {
    expect(ask({ ...regular, supported: true })).toBe(false);
  });

  it("only over a fresh forecast", () => {
    expect(ask(regular, "stale")).toBe(false);
    expect(ask(regular, "fallback")).toBe(false);
    expect(ask(regular, "error")).toBe(false);
  });

  it("asks up to category 2, never in a flood", () => {
    expect(ask(regular, "fresh", 2)).toBe(true);
    expect(ask(regular, "fresh", 3)).toBe(false);
  });

  it("stays away for the rest of the day after closing", () => {
    const dismissed = { ...regular, dismissedMs: morning };
    expect(shouldPrompt(dismissed, after, "fresh", 1, lateEvening)).toBe(false);
    expect(shouldPrompt(dismissed, after, "fresh", 1, afterMidnight)).toBe(
      true,
    );
  });
});

describe("parseThanks", () => {
  it("finds the tier", () => {
    expect(parseThanks("?danke=dezimeter", support.tiers)?.tier?.name).toBe(
      "Dezimeter",
    );
  });

  it("shows the card without a tier for one-off or unknown values", () => {
    expect(parseThanks("?danke=einmalig", support.tiers)).toEqual({
      tier: null,
    });
    expect(parseThanks("?danke=kilometer", support.tiers)).toEqual({
      tier: null,
    });
  });

  it("is null without the parameter", () => {
    expect(parseThanks("?fixture=normal", support.tiers)).toBeNull();
    expect(parseThanks("", support.tiers)).toBeNull();
  });
});

describe("withoutThanks", () => {
  it("keeps the other parameters", () => {
    expect(withoutThanks("?fixture=normal&danke=meter&hover=x")).toBe(
      "?fixture=normal&hover=x",
    );
    expect(withoutThanks("?danke=meter")).toBe("");
  });
});
