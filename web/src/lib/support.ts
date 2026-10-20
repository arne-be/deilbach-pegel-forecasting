// Pure logic for the support prompt and the thank-you card. No DOM, no storage, no clock.
import type { SupportTier } from "./config";
import type { State, Verdict } from "./forecast";
import { berlinDayWord } from "./format";

/** What the page remembers on this device, under one localStorage key. */
export interface SupportMemory {
  visits: number;
  /** Time of the last counted visit (ms), so a day counts once by the Berlin calendar. */
  lastVisitMs: number | null;
  /** Time the prompt was last closed; it stays away for the rest of that Berlin day. */
  dismissedMs: number | null;
  /** Came back through a Stripe thank-you link or clicked a tier. Not proof of payment. */
  supported: boolean;
}

export const firstVisit: SupportMemory = {
  visits: 0,
  lastVisitMs: null,
  dismissedMs: null,
  supported: false,
};

const isTime = (value: unknown): value is number | null =>
  value === null || Number.isFinite(value);

/** Reads the stored JSON; anything missing or malformed counts as a first visit. */
export function parseMemory(raw: string | null): SupportMemory {
  if (raw === null) return firstVisit;
  try {
    const stored = JSON.parse(raw) as Partial<SupportMemory>;
    if (
      !Number.isInteger(stored.visits) ||
      !isTime(stored.lastVisitMs ?? null) ||
      !isTime(stored.dismissedMs ?? null) ||
      typeof stored.supported !== "boolean"
    ) {
      return firstVisit;
    }
    return {
      visits: stored.visits as number,
      lastVisitMs: stored.lastVisitMs ?? null,
      dismissedMs: stored.dismissedMs ?? null,
      supported: stored.supported,
    };
  } catch {
    return firstVisit;
  }
}

const sameBerlinDay = (ms: number | null, nowMs: number) =>
  ms !== null && berlinDayWord(ms, nowMs) === "heute";

/** Counts at most one visit per Berlin calendar day, so reloads during a flood don't add up. */
export function recordVisit(
  memory: SupportMemory,
  nowMs: number,
): SupportMemory {
  if (sameBerlinDay(memory.lastVisitMs, nowMs)) return memory;
  return { ...memory, visits: memory.visits + 1, lastVisitMs: nowMs };
}

/** The highest category now or in the forecast, including what its 90 % range makes possible. */
export function peakCategory(
  currentNumber: number,
  forecastVerdict: Verdict | null,
): number {
  return Math.max(
    currentNumber,
    forecastVerdict?.expected.number ?? 0,
    forecastVerdict?.possible?.category.number ?? 0,
  );
}

/**
 * Only for regular visitors on a calm, current page: never during a flood or over old data.
 * `categoryNumber` is the `peakCategory`, so an expected or possible flood counts too.
 */
export function shouldPrompt(
  memory: SupportMemory,
  afterVisits: number | null,
  state: State,
  categoryNumber: number,
  nowMs: number,
): boolean {
  return (
    afterVisits !== null &&
    memory.visits >= afterVisits &&
    !memory.supported &&
    state === "fresh" &&
    categoryNumber <= 2 &&
    !sameBerlinDay(memory.dismissedMs, nowMs)
  );
}

const THANKS_PARAM = "danke";

/** `?danke=<tier id>` gives that tier; `?danke=einmalig` or an unknown value gives `tier: null`. */
export function parseThanks(
  search: string,
  tiers: readonly SupportTier[],
): { tier: SupportTier | null } | null {
  const value = new URLSearchParams(search).get(THANKS_PARAM);
  if (value === null) return null;
  return { tier: tiers.find((tier) => tier.id === value) ?? null };
}

/** The query string without `danke`, other parameters kept: "?fixture=normal" or "". */
export function withoutThanks(search: string): string {
  const query = new URLSearchParams(search);
  query.delete(THANKS_PARAM);
  const rest = query.toString();
  return rest ? `?${rest}` : "";
}
