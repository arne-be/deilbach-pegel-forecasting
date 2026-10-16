// Category chip: "3 · sehr kritisch" in its colour; dashed when only possible, grey when out of date.
import type { CSSProperties } from "react";
import type { Category } from "../lib/config";

interface ChipProps {
  category: Category;
  variant?: "ghost" | "off";
}

export default function Chip({ category, variant }: ChipProps) {
  const tone = `var(--c${category.number})`;
  const classes = ["chip", category.number >= 3 && "dark", variant];
  return (
    <span
      className={classes.filter(Boolean).join(" ")}
      style={{ "--chip": tone } as CSSProperties}
    >
      {category.number} · {category.name}
    </span>
  );
}
