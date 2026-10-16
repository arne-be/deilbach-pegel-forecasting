// The headline: the expected category in the next hours, or a badge saying why there is none.
import { horizonHours } from "../lib/config";
import type { State, Verdict as VerdictData } from "../lib/forecast";
import { berlinHourPhrase } from "../lib/format";
import Chip from "./Chip";

export const PORTAL_URL = "https://www.hochwasserportal.nrw.de";

interface VerdictProps {
  state: State;
  /** Null unless `state` is "fresh". */
  verdict: VerdictData | null;
  /** When the newest reading was taken, e.g. "16:22 Uhr"; null without data. */
  reading: string | null;
  nowMs: number;
}

const BADGES: Record<State, string> = {
  fresh: "Keine Daten", // not reached: a fresh state always comes with a verdict
  stale: "Veraltet",
  fallback: "Keine Prognose",
  error: "Keine Daten",
};

export default function Verdict({
  state,
  verdict,
  reading,
  nowMs,
}: VerdictProps) {
  if (state !== "fresh" || verdict === null) {
    const badge = BADGES[state];
    return (
      <p className="verdict" role="status">
        <span className="line">
          <span className="badge">
            {reading ? `${badge} · ${reading}` : badge}
          </span>
        </span>
        <span className="line">
          <a className="portal" href={PORTAL_URL}>
            Hochwasserportal NRW
          </a>
        </span>
      </p>
    );
  }
  const { expected, expectedAt, possible } = verdict;
  return (
    <p className="verdict" role="status">
      <span className="line">
        Voraussichtlich {expected.number > 1 && !expectedAt && "weiter "}
        <Chip category={expected} />{" "}
        {expectedAt ? (
          <span className="when">
            {berlinHourPhrase(expectedAt.atMs, nowMs, "gegen")}
          </span>
        ) : (
          expected.number === 1 && `in den nächsten ${horizonHours} Stunden`
        )}
      </span>
      {possible && (
        <span className="line">
          Möglich: <Chip category={possible.category} variant="ghost" />{" "}
          <span className="when">
            {berlinHourPhrase(possible.atMs, nowMs, "ab")}
          </span>
        </span>
      )}
    </p>
  );
}
