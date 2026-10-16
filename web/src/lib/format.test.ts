import { describe, expect, it } from "vitest";
import {
  berlinClock,
  berlinDayWord,
  berlinHourPhrase,
  formatCm,
} from "./format";

const now = Date.parse("2026-11-19T15:41:00Z"); // Thursday, 16:41 in Berlin

describe("formatCm", () => {
  it("writes German numbers", () => {
    expect(formatCm(128)).toBe("128 cm");
    expect(formatCm(145.8)).toBe("146 cm");
    expect(formatCm(68.5, 1)).toBe("68,5 cm");
    expect(formatCm(145, 1)).toBe("145,0 cm");
  });
});

describe("berlinClock", () => {
  it("shows Berlin time with leading zeros", () => {
    expect(berlinClock(Date.parse("2026-11-19T15:22:02Z"))).toBe("16:22 Uhr");
    expect(berlinClock(Date.parse("2026-10-16T05:02:00Z"))).toBe("07:02 Uhr");
  });
});

describe("berlinHourPhrase", () => {
  it("says heute, morgen or the weekday by the Berlin calendar day", () => {
    expect(berlinHourPhrase(Date.parse("2026-11-19T20:22:00Z"), now)).toBe(
      "heute 21 Uhr",
    );
    // Still the 19th in UTC, already the 20th in Berlin.
    expect(berlinHourPhrase(Date.parse("2026-11-19T23:22:00Z"), now)).toBe(
      "morgen 0 Uhr",
    );
    expect(berlinHourPhrase(Date.parse("2026-11-20T02:22:00Z"), now)).toBe(
      "morgen 3 Uhr",
    );
    expect(berlinHourPhrase(Date.parse("2026-11-21T02:22:00Z"), now)).toBe(
      "Sa. 3 Uhr",
    );
    expect(berlinHourPhrase(Date.parse("2026-11-18T22:22:00Z"), now)).toBe(
      "gestern 23 Uhr",
    );
  });

  it("keeps morgen right across the switch to summer time", () => {
    // 23:30 on Saturday 28 March; Sunday has only 23 hours.
    const saturdayNight = Date.parse("2026-03-28T22:30:00Z");
    expect(
      berlinHourPhrase(Date.parse("2026-03-29T21:00:00Z"), saturdayNight),
    ).toBe("morgen 23 Uhr");
    expect(
      berlinHourPhrase(Date.parse("2026-03-29T22:30:00Z"), saturdayNight),
    ).toBe("Mo. 0 Uhr");
  });
});

describe("berlinHourPhrase with a word", () => {
  it("puts it between the day and the hour", () => {
    const ms = Date.parse("2026-11-19T20:22:00Z");
    expect(berlinHourPhrase(ms, now, "gegen")).toBe("heute gegen 21 Uhr");
    expect(berlinHourPhrase(ms + 6 * 3_600_000, now, "ab")).toBe(
      "morgen ab 3 Uhr",
    );
  });
});

describe("berlinDayWord", () => {
  it("names the day only", () => {
    expect(berlinDayWord(now, now)).toBe("heute");
    expect(berlinDayWord(Date.parse("2026-11-21T02:22:00Z"), now)).toBe("Sa.");
  });
});
