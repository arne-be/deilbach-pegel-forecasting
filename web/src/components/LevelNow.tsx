// The newest reading, its category and how far it is from the first flood threshold.
import { categoryFor, distanceToCritical, type State } from "../lib/forecast";
import { formatCm } from "../lib/format";
import Chip from "./Chip";

interface LevelNowProps {
  levelCm: number;
  /** When it was taken, e.g. "16:22 Uhr". */
  reading: string;
  state: State;
}

export default function LevelNow({ levelCm, reading, state }: LevelNowProps) {
  const stale = state === "stale";
  const gap = distanceToCritical(levelCm);
  const critical = formatCm(levelCm + gap);
  return (
    <div className="level">
      <p className="nowrow">
        <span className="big">{formatCm(levelCm)}</span>
        <Chip
          category={categoryFor(levelCm)}
          variant={stale ? "off" : undefined}
        />
        <span className="sub">gemessen {reading}</span>
      </p>
      {!stale && (
        <p className="dist">
          {gap >= 0 ? (
            <>
              Bis kritisch ({critical}): noch <b>{formatCm(Math.floor(gap))}</b>
            </>
          ) : (
            <>
              Kritische Marke ({critical}) um <b>{formatCm(Math.ceil(-gap))}</b>{" "}
              überschritten
            </>
          )}
        </p>
      )}
    </div>
  );
}
