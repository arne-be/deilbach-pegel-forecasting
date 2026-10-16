// "Stufen und Maßnahmen": one card per category, tagged with when the forecast reaches it.
import type { CSSProperties } from "react";
import { categories } from "../lib/config";
import type { CategoryTag } from "../lib/forecast";
import { berlinHourPhrase } from "../lib/format";
import Chip from "./Chip";

interface CategoryCardsProps {
  /** From `categoryTags`; null without data, which leaves plain cards. */
  tags: Map<number, CategoryTag> | null;
  /** False when stale: the current category isn't outlined then. */
  outlineCurrent: boolean;
  nowMs: number;
}

function rangeText(index: number): string {
  const from = categories[index].above_cm;
  const next = categories[index + 1]?.above_cm;
  if (from === null) return `bis ${next} cm`;
  return next === undefined ? `über ${from} cm` : `${from}–${next} cm`;
}

export default function CategoryCards({
  tags,
  outlineCurrent,
  nowMs,
}: CategoryCardsProps) {
  return (
    <section className="levels" aria-labelledby="levels-title">
      <h2 className="label" id="levels-title">
        Stufen und Maßnahmen
      </h2>
      <ol>
        {categories.map((category, index) => {
          const tag = tags?.get(category.number);
          const outlined = Boolean(tag?.current && outlineCurrent);
          const maybe = tag?.possibleFromMs != null;
          // Neither current nor reached within the horizon: muted, still readable.
          const off = tag !== undefined && !tag.current && !tag.reached;
          const classes = [
            "card",
            outlined && "now",
            maybe && "maybe",
            off && "off",
          ];
          return (
            <li
              key={category.number}
              className={classes.filter(Boolean).join(" ")}
              style={
                { "--tone": `var(--c${category.number})` } as CSSProperties
              }
              aria-current={outlined ? "true" : undefined}
            >
              <div className="head">
                <Chip category={category} />
                <span className="range">{rangeText(index)}</span>
              </div>
              {tag?.expectedAtMs != null && (
                <span className="tag">
                  erwartet {berlinHourPhrase(tag.expectedAtMs, nowMs, "gegen")}
                </span>
              )}
              {tag?.possibleFromMs != null && (
                <span className="tag maybe">
                  möglich {berlinHourPhrase(tag.possibleFromMs, nowMs, "ab")}
                </span>
              )}
              <p>
                {category.description} {category.actions}
              </p>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
