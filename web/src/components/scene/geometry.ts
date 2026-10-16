// Projection, layout and drawing helpers of the site scene. Pure: no DOM, safe to import during SSR.
import { categories } from "../../lib/config";

export type P3 = readonly [number, number, number];

/** Category thresholds in cm, ascending (145, 165, 185, 225 in config/pegel.json). */
export const THRESHOLDS: readonly number[] = categories.flatMap((category) =>
  category.above_cm === null ? [] : [category.above_cm],
);
if (THRESHOLDS.length !== 4) {
  throw new Error(
    `The scene draws 5 categories, config has ${categories.length}`,
  );
}
const [cat2, cat3, cat4, cat5] = THRESHOLDS as [number, number, number, number];

// The categories are defined by the site, so its heights follow them: the car park floods above category 2,
// the wall tops out at category 3, barriers hold to category 4, sandbags and the house floor sit at category 5.
export const LEVELS = {
  park: cat2,
  wall: cat3,
  barriersUp: cat2,
  sandbags: cat3,
  barrierTop: cat4,
  bagTop: cat5,
  floor: cat5,
  muddy: cat5,
};

// Layout: u across the valley, v along the river (both in scene units), z in cm.
export const BAGS = { u0: 584, u1: 600, v0: 46 };
export const LV = 250;
export const BOTTOM = -40;
export const UMAX = 800;
export const PARK_U = 240;
export const BED_U = 262;
export const WALL_U0 = 470;
export const WALL_U1 = 486;
export const BAR_U = 488;
export const HOUSE = { u0: 640, v0: 70, eave: 415, ridge: 487, ridgeU: 720 };
export const STAFF = { u: 466, v0: 8, v1: 56, top: 255 };
export const DOOR = { v0: 170, v1: 196 };

// Axonometric projection: u rises 12° to the right, v recedes 30° up-left (foreshortened), z is cm × 0.8.
const A = (12 * Math.PI) / 180;
const B = (30 * Math.PI) / 180;
export const KV = 0.72;
const Z = 0.8;
export const CA = Math.cos(A);
export const SA = Math.sin(A);
export const CB = Math.cos(B);
export const SB = Math.sin(B);
export const pt = (u: number, v: number, z: number): [number, number] => [
  u * CA - v * KV * CB,
  -u * SA - v * KV * SB - z * Z,
];
export const ptOf = (p: P3): [number, number] => pt(p[0], p[1], p[2]);

/** Faces below `cut.clip` are cut off (the water surface); set it before drawing, reset after. */
export const cut = { clip: Number.NEGATIVE_INFINITY };

// ---- drawing helpers: every face is a filled polygon, no outlines ----
export const f1 = (n: number): number => Math.round(n * 10) / 10;
export const op = (x: number): number => f1(x * 100) / 100;
export const pathD = (pts: readonly P3[]): string =>
  `M${pts
    .map((p) => {
      const q = ptOf(p);
      return `${f1(q[0])},${f1(q[1])}`;
    })
    .join("L")}Z`;
export const path = (pts: readonly P3[], cls: string): string =>
  `<path class="${cls}" d="${pathD(pts)}"/>`;
export const line = (a: P3, b: P3): string => {
  const p = ptOf(a);
  const q = ptOf(b);
  return `M${f1(p[0])},${f1(p[1])}L${f1(q[0])},${f1(q[1])}`;
};

export function qU(
  u: number,
  v0: number,
  v1: number,
  z0: number,
  z1: number,
  cls: string,
): string {
  const zb = Math.max(z0, cut.clip);
  return z1 <= zb
    ? ""
    : path(
        [
          [u, v0, zb],
          [u, v1, zb],
          [u, v1, z1],
          [u, v0, z1],
        ],
        cls,
      );
}
export function qV(
  v: number,
  u0: number,
  u1: number,
  z0: number,
  z1: number,
  cls: string,
): string {
  const zb = Math.max(z0, cut.clip);
  return z1 <= zb
    ? ""
    : path(
        [
          [u0, v, zb],
          [u1, v, zb],
          [u1, v, z1],
          [u0, v, z1],
        ],
        cls,
      );
}
export function qT(
  z: number,
  u0: number,
  u1: number,
  v0: number,
  v1: number,
  cls: string,
): string {
  return z < cut.clip
    ? ""
    : path(
        [
          [u0, v0, z],
          [u1, v0, z],
          [u1, v1, z],
          [u0, v1, z],
        ],
        cls,
      );
}
export function box(
  u0: number,
  u1: number,
  v0: number,
  v1: number,
  z0: number,
  z1: number,
  m: string,
): string {
  return (
    qU(u0, v0, v1, z0, z1, `${m}-l`) +
    qV(v0, u0, u1, z0, z1, `${m}-f`) +
    qT(z1, u0, u1, v0, v1, `${m}-t`)
  );
}
/** Ellipse in a -v plane, flattened at the clip height. */
export function ringV(
  v: number,
  cu: number,
  cz: number,
  ru: number,
  rz: number,
  cls: string,
): string {
  if (cz + rz <= cut.clip) return "";
  const pts: P3[] = [];
  for (let i = 0; i < 16; i++) {
    const a = (i / 16) * 2 * Math.PI;
    pts.push([
      cu + ru * Math.cos(a),
      v,
      Math.max(cut.clip, cz + rz * Math.sin(a)),
    ]);
  }
  return path(pts, cls);
}

// ---- view boxes: the whole site, or on narrow containers the wall, staff, barriers and house front ----
function bbox(points: P3[], pad: number): number[] {
  const xs = points.map((p) => pt(...p)[0]);
  const ys = points.map((p) => pt(...p)[1]);
  const x0 = Math.min(...xs) - pad;
  const y0 = Math.min(...ys) - pad;
  return [x0, y0, Math.max(...xs) + pad - x0, Math.max(...ys) + pad - y0].map(
    f1,
  );
}
const corners = (
  u0: number,
  u1: number,
  v0: number,
  v1: number,
  z0: number,
  z1: number,
): P3[] =>
  [u0, u1].flatMap((u) =>
    [v0, v1].flatMap((v): P3[] => [
      [u, v, z0],
      [u, v, z1],
    ]),
  );
export const VB_WIDE = bbox(
  [
    ...corners(0, UMAX, 0, LV, BOTTOM - 14, LEVELS.wall),
    ...corners(HOUSE.u0 - 10, UMAX, HOUSE.v0 - 8, LV, 0, HOUSE.ridge + 30),
    [36, 232, 260],
  ],
  14,
);
export const VB_NARROW = (() => {
  const x0 = pt(180, 0, 0)[0];
  const x1 = pt(740, HOUSE.v0, 0)[0];
  const y0 =
    Math.min(
      pt(684, 196, HOUSE.ridge + 30)[1],
      pt(HOUSE.ridgeU, HOUSE.v0, HOUSE.ridge)[1],
    ) - 18;
  const y1 = Math.max(pt(180, 0, BOTTOM - 10)[1], pt(740, 0, BOTTOM - 10)[1]);
  return [x0, y0, x1 - x0, y1 - y0].map(f1);
})();
