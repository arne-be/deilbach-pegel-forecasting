// German display of levels and times. Times are stored in UTC and shown in Europe/Berlin.
const TIME_ZONE = "Europe/Berlin";
const DAY_MS = 86_400_000;

const clockFormat = new Intl.DateTimeFormat("de-DE", {
  timeZone: TIME_ZONE,
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
const hourFormat = new Intl.DateTimeFormat("de-DE", {
  timeZone: TIME_ZONE,
  hour: "numeric",
  hourCycle: "h23",
});
const weekdayFormat = new Intl.DateTimeFormat("de-DE", {
  timeZone: TIME_ZONE,
  weekday: "short",
});
// en-CA formats as YYYY-MM-DD, which Date.parse reads as a UTC midnight.
const dateFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** "128 cm", "68,5 cm". */
export function formatCm(levelCm: number, decimals: 0 | 1 = 0): string {
  const number = levelCm.toLocaleString("de-DE", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return `${number} cm`;
}

/** "16:22 Uhr". */
export function berlinClock(ms: number): string {
  return `${clockFormat.format(ms)} Uhr`;
}

// Calendar day in Berlin as a day count, so "tomorrow" stays right across DST changes.
function berlinDay(ms: number): number {
  return Date.parse(dateFormat.format(ms)) / DAY_MS;
}

/** "heute 21 Uhr", "morgen 3 Uhr", "Fr. 3 Uhr". */
export function berlinHourPhrase(ms: number, nowMs: number): string {
  const hourPart = hourFormat
    .formatToParts(ms)
    .find((part) => part.type === "hour");
  const hour = `${Number(hourPart?.value)} Uhr`;
  const daysAhead = berlinDay(ms) - berlinDay(nowMs);
  if (daysAhead === 0) return `heute ${hour}`;
  if (daysAhead === 1) return `morgen ${hour}`;
  // Some ICU versions write "Fr", others "Fr.".
  return `${weekdayFormat.format(ms).replace(/\.?$/, ".")} ${hour}`;
}
