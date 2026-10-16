// The water at a level and the skip container that drifts on it in category 5.
import {
  BAGS,
  BAR_U,
  BED_U,
  CB,
  f1,
  HOUSE,
  KV,
  LEVELS,
  LV,
  line,
  op,
  type P3,
  PARK_U,
  path,
  pathD,
  pt,
  ptOf,
  qU,
  SB,
  UMAX,
  WALL_U0,
} from "./geometry";

/** Left edge of the water: the river bank, then the whole car park. */
const uLeft = (L: number): number =>
  L >= LEVELS.park
    ? 0
    : PARK_U + ((BED_U - PARK_U) * (LEVELS.park - L)) / LEVELS.park;
/** Right edge of the water: the wall, then the barriers, then the sandbags, then the house. */
const uRight = (L: number): number =>
  L <= LEVELS.wall
    ? WALL_U0
    : L <= LEVELS.barrierTop
      ? BAR_U
      : L <= LEVELS.bagTop
        ? BAGS.u0
        : HOUSE.u0;

/** Flood water turns muddy brown across the category 5 threshold (0 clear, 1 brown). */
export const muddiness = (L: number): number => {
  const x = Math.min(1, Math.max(0, (L - (LEVELS.muddy - 6)) / 12));
  return x * x * (3 - 2 * x);
};

/** One flat surface at the level, filling everything lower up to the next higher obstacle. */
export function water(L: number, stale: boolean): string {
  if (L <= 0.5) return "";
  const uL = uLeft(L);
  const uR = uRight(L);
  const mud = stale ? 0 : muddiness(L);
  const top: P3[] = [
    [uL, 0, L],
    [uR, 0, L],
    [uR, LV, L],
    [uL, LV, L],
  ];
  // Over the barriers the yard floods up to the sandbags (the strip in front of them too); over the bags, up to the house.
  const frontV = L > LEVELS.bagTop ? HOUSE.v0 : BAGS.v0;
  const yard: P3[] | null =
    L > LEVELS.barrierTop
      ? [
          [uR, 0, L],
          [UMAX, 0, L],
          [UMAX, frontV, L],
          [uR, frontV, L],
        ]
      : null;
  // The surface stays translucent: clear blue cross-fades into muddy brown, so what is under it shows through.
  let o = `<g opacity="${op(1 - mud)}">${path(top, "sc-water-t")}${yard ? path(yard, "sc-water-t") : ""}</g>`;
  if (mud > 0)
    o += `<g opacity="${op(mud)}">${path(top, "sc-mud-t")}${yard ? path(yard, "sc-mud-t") : ""}</g>`;
  // A light rim where the surface meets walls: the wall or barriers, and the house when it is reached.
  const rims = yard
    ? line([uR, LV, L], [uR, frontV, L]) +
      line([uR, frontV, L], [UMAX, frontV, L])
    : line([uR, 0, L], [uR, LV, L]);
  o += `<path class="sc-rim" d="${rims}"/>`;
  if (uL === 0)
    o +=
      qU(0, 0, LV, LEVELS.park, L, "sc-water-l") +
      (mud > 0
        ? `<g opacity="${op(mud)}">${qU(0, 0, LV, LEVELS.park, L, "sc-mud-f")}</g>`
        : "");
  // front cut: the region between the terrain profile and the surface
  const uR0 = L > LEVELS.barrierTop ? UMAX : uR;
  const prof = [
    [0, LEVELS.park],
    [PARK_U, LEVELS.park],
    [BED_U, 0],
    [WALL_U0, 0],
    [WALL_U0, LEVELS.wall],
    [UMAX, LEVELS.wall],
  ] as const;
  const pts: P3[] = [[uL, 0, L]];
  for (const [u, z] of prof)
    if (u >= uL && u < uR0) pts.push([u, 0, Math.min(z, L)]);
  if (uR0 === WALL_U0) pts.push([WALL_U0, 0, 0]);
  else pts.push([uR0, 0, LEVELS.wall]);
  pts.push([uR0, 0, L]);
  o += path(pts, "sc-water-f");
  if (mud > 0) o += `<g opacity="${op(mud)}">${path(pts, "sc-mud-f")}</g>`;
  o += `<path class="sc-water-hi" d="${line([uL, 0, L], [uR0, 0, L])}"/>`;
  // Ripples: dashed lines along the river, clipped to the surface. A CSS animation slides each layer one dash
  // period downstream (towards the front, left to right on screen) and loops, so no frame rebuilds a path.
  o += `<clipPath id="sc-wclip"><path d="${pathD(top)}"/></clipPath><g clip-path="url(#sc-wclip)">`;
  const span = uR - uL;
  const count = Math.max(1, Math.floor(span / 26));
  const layer = (
    cls: string,
    P: number,
    dash: number,
    offset: number,
    opacity = 1,
  ) => {
    let g = `<g class="sc-flow ${cls}" style="--fx:${op(P * KV * CB)}px;--fy:${op(P * KV * SB)}px"${opacity < 1 ? ` opacity="${op(opacity)}"` : ""}>`;
    for (let i = 0; i < count; i++) {
      const u = uL + (span * (i + offset)) / count;
      g += `<path d="${line([u, LV + 2 * P + ((i * 37) % P), L], [u, -P, L])}" stroke-dasharray="${dash} ${f1(P * KV - dash)}"/>`;
    }
    return `${g}</g>`;
  };
  o +=
    layer("sc-flow-a sc-ripple", 44, 11, 0.3, 1 - mud * 0.6) +
    layer("sc-flow-b sc-ripple", 70, 22, 0.75, 1 - mud * 0.6);
  if (mud > 0)
    o +=
      layer("sc-flow-c sc-foam", 80, 30, 0.5, mud) +
      layer("sc-flow-a sc-foam sc-foam-thin", 52, 14, 0.15, mud * 0.5);
  return `${o}</g>`;
}

/** Keep the part of a planar polygon at or above zmin. */
function clipPoly(pts: readonly P3[], zmin: number): P3[] {
  const out: P3[] = [];
  pts.forEach((p, i) => {
    const q = pts[(i + 1) % pts.length] as P3;
    const pin = p[2] >= zmin;
    const qin = q[2] >= zmin;
    if (pin) out.push(p);
    if (pin !== qin) {
      const t = (zmin - p[2]) / (q[2] - p[2]);
      out.push([p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t, zmin]);
    }
  });
  return out;
}

export const SKIP_U = 372;

/** The skip container (Absetzmulde), drawn at v = 0; the engine moves it downstream with a transform. */
export function container(L: number): string {
  // Local box: tapered sides and sloped ends, tilted nose-down towards the front and rolled away from the viewer,
  // so its river-side wall faces up into view and its front corner dips under the surface.
  const zb = L - 28;
  const zt = L + 30;
  const tilt = 0.4;
  const roll = 0.12;
  const P = (u: number, v: number, z: number): P3 => [
    SKIP_U + u,
    v,
    z + v * tilt + u * roll,
  ];
  const T = [
    [-23, -66],
    [50, -66],
    [50, 66],
    [-23, 66],
  ] as const;
  const Bm = [
    [-30, -44],
    [30, -44],
    [30, 44],
    [-30, 44],
  ] as const;
  const tp = (i: 0 | 1 | 2 | 3) => P(T[i][0], T[i][1], zt);
  const bp = (i: 0 | 1 | 2 | 3) => P(Bm[i][0], Bm[i][1], zb);
  const face = (pts: readonly P3[], cls: string) => {
    const c = clipPoly(pts, L);
    return c.length > 2 ? path(c, cls) : "";
  };
  const lerp = (p: P3, q: P3, t: number): P3 => [
    p[0] + (q[0] - p[0]) * t,
    p[1] + (q[1] - p[1]) * t,
    p[2] + (q[2] - p[2]) * t,
  ];
  const flat = (u: number, v: number): P3 => [SKIP_U + u, v, L];
  const poly = (ps: readonly (readonly [number, number])[]) =>
    ps
      .map(([u, v]) =>
        pt(SKIP_U + u, v, L)
          .map(f1)
          .join(","),
      )
      .join("L");
  let o = `<g class="sc-skip">`;
  // turbulence: a churned patch around the hull and two wake streaks trailing upstream, then a foam collar
  o += `<path class="sc-skip-churn" d="M${poly([
    [-46, -80],
    [52, -78],
    [66, 10],
    [50, 86],
    [-44, 84],
    [-58, 0],
  ])}Z"/>`;
  o += `<path class="sc-skip-wake" d="M${poly([
    [-36, 50],
    [-58, 190],
    [-48, 190],
    [-28, 56],
  ])}ZM${poly([
    [40, 50],
    [68, 190],
    [58, 190],
    [34, 56],
  ])}Z"/>`;
  o += path(
    [flat(-36, -62), flat(42, -62), flat(42, 62), flat(-36, 62)],
    "sc-skip-foam",
  );
  // inside: the floor, the far side wall and the back end wall (lit), seen over the near rim
  const ti = (i: 0 | 1 | 2 | 3) =>
    P(T[i][0] + (i === 0 || i === 3 ? 7 : -7), T[i][1] * 0.9, zt);
  const bi = (i: 0 | 1 | 2 | 3) => P(Bm[i][0] * 0.82, Bm[i][1] * 0.88, zb + 6);
  o += face([bi(0), bi(1), bi(2), bi(3)], "sc-skip-floor");
  o += face([ti(1), ti(2), bi(2), bi(1)], "sc-skip-in");
  o += face([ti(3), ti(2), bi(2), bi(3)], "sc-skip-in2");
  // outside: the river-side wall and the front end, cut at the waterline with a foam line, then rim, rust, stripes
  const waterline = (pts: readonly P3[]) => {
    const c = clipPoly(pts, L).filter((p) => Math.abs(p[2] - L) < 1e-6);
    return c.length === 2
      ? `M${ptOf(c[0] as P3)
          .map(f1)
          .join(",")}L${ptOf(c[1] as P3)
          .map(f1)
          .join(",")}`
      : "";
  };
  const side = [tp(0), tp(3), bp(3), bp(0)];
  const front = [tp(0), tp(1), bp(1), bp(0)];
  o += face(side, "sc-skip-l") + face(front, "sc-skip-f");
  o += `<path class="sc-skip-line" d="${waterline(side)}${waterline(front)}"/>`;
  o += path(
    [tp(0), tp(1), tp(2), tp(3), ti(3), ti(2), ti(1), ti(0)],
    "sc-skip-t",
  );
  o += face(
    [tp(0), tp(3), lerp(tp(3), bp(3), 0.12), lerp(tp(0), bp(0), 0.12)],
    "sc-skip-rust",
  );
  for (let s = 0; s < 3; s++) {
    const a = 0.18 + s * 0.09;
    const s0 = lerp(tp(0), tp(1), a);
    const s1 = lerp(tp(0), tp(1), a + 0.05);
    o += face(
      [
        lerp(s0, bp(0), 0.18),
        lerp(s1, bp(1), 0.18),
        lerp(s1, bp(1), 0.5),
        lerp(s0, bp(0), 0.5),
      ],
      s % 2 ? "sc-skip-white" : "sc-skip-red",
    );
  }
  const sideAt = (a: number, t: number) =>
    lerp(lerp(tp(0), tp(3), a), lerp(bp(0), bp(3), a), t);
  o += face(
    [
      sideAt(0.55, 0.22),
      sideAt(0.7, 0.22),
      sideAt(0.7, 0.42),
      sideAt(0.55, 0.42),
    ],
    "sc-skip-patch",
  );
  return `${o}</g>`;
}
