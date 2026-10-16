// The solid parts of the scene: terrain, car park, staff, house, barriers, sandbags, trees, cars.
import {
  BAGS,
  BAR_U,
  BED_U,
  BOTTOM,
  box,
  CA,
  CB,
  cut,
  f1,
  HOUSE,
  LEVELS,
  LV,
  op,
  PARK_U,
  path,
  pt,
  qT,
  qU,
  qV,
  ringV,
  SA,
  SB,
  STAFF,
  THRESHOLDS,
  UMAX,
  WALL_U0,
  WALL_U1,
} from "./geometry";

export function terrainBack(k: number): string {
  let o = "";
  o += qT(LEVELS.wall, WALL_U1, UMAX, 0, LV, "sc-grass-t");
  o += qT(LEVELS.wall, 596, HOUSE.u0, HOUSE.v0 - 8, LV, "sc-pave-t");
  o += qT(LEVELS.wall, 596, UMAX, 30, HOUSE.v0 - 8, "sc-pave-t");
  o += qT(0, BED_U, WALL_U0, 0, LV, "sc-bed-t");
  o += path(
    [
      [PARK_U, 0, LEVELS.park],
      [BED_U, 0, 0],
      [BED_U, LV, 0],
      [PARK_U, LV, LEVELS.park],
    ],
    "sc-bank",
  );
  o += qU(WALL_U0, 0, LV, 0, LEVELS.wall, "sc-con-l");
  for (let v = 40; v < LV; v += 52)
    o += qU(WALL_U0 - 0.2, v, v + 0.9, 0, LEVELS.wall, "sc-joint");
  o += qU(WALL_U0 - 0.2, 0, LV, 0, 58, "sc-stain");
  o += qT(LEVELS.wall, WALL_U0, WALL_U1, 0, LV, "sc-con-t");
  return o + staff(k);
}

export function frontSection(): string {
  let o = "";
  o += path(
    [
      [0, 0, BOTTOM],
      [0, 0, LEVELS.park],
      [PARK_U, 0, LEVELS.park],
      [BED_U, 0, 0],
      [WALL_U0, 0, 0],
      [WALL_U0, 0, 20],
      [UMAX, 0, 20],
      [UMAX, 0, BOTTOM],
    ],
    "sc-soil-f",
  );
  o += qV(0, WALL_U1, UMAX, 20, LEVELS.wall, "sc-soil-f");
  o += qV(0, 0, UMAX, BOTTOM, BOTTOM + 18, "sc-soil-d");
  for (const z of [30, 80])
    o +=
      qV(0, 0, PARK_U - 2, z, z + 1.5, "sc-strata") +
      qV(0, WALL_U1, UMAX, z + 10, z + 11.5, "sc-strata");
  o += qV(0, WALL_U1, UMAX, 125, 126.5, "sc-strata");
  o += qV(0, BED_U - 4, WALL_U0, -7, 0, "sc-bed-f");
  o += qV(0, 0, PARK_U - 2, LEVELS.park - 8, LEVELS.park, "sc-park-f");
  o += qV(0, WALL_U1, UMAX, LEVELS.wall - 6, LEVELS.wall, "sc-grass-f");
  o += qV(0, WALL_U0, WALL_U1, -25, LEVELS.wall, "sc-con-f");
  o += qV(0, 596, UMAX, LEVELS.wall - 6, LEVELS.wall, "sc-pave-f");
  return o;
}

export function carPark(): string {
  let o = "";
  o +=
    qU(0, 0, LV, BOTTOM, BOTTOM + 18, "sc-soil-d") +
    qU(0, 0, LV, BOTTOM + 18, LEVELS.park - 8, "sc-soil-l") +
    qU(0, 0, LV, LEVELS.park - 8, LEVELS.park, "sc-park-l");
  o += qT(LEVELS.park, 0, PARK_U, 0, LV, "sc-park-t");
  for (const v of [12, 86, 164, 238])
    o += qT(LEVELS.park, 40, 214, v - 1, v + 1, "sc-line");
  o += qT(LEVELS.park, 214, 216, 12, 238, "sc-line");
  o += box(PARK_U - 10, PARK_U, 0, LV, LEVELS.park, LEVELS.park + 5, "sc-con");
  return o;
}

/** The gauge staff on the wall's river face, painted in the category colours with their numbers. */
export function staff(k: number): string {
  const { u, v0, v1, top } = STAFF;
  let o = box(u + 8, u + 14, v0 + 8, v1 - 8, LEVELS.wall, top - 4, "sc-post");
  o += qV(v0, u - 2.5, u, 0, top, "sc-board-edge");
  o += qT(top, u - 2.5, u, v0, v1, "sc-board-edge");
  const bounds = [0, ...THRESHOLDS, top];
  for (let i = 0; i < 5; i++)
    o += qU(
      u - 2.5,
      v0,
      v1,
      bounds[i] ?? 0,
      bounds[i + 1] ?? 0,
      `sc-c${i + 1}`,
    );
  for (let cm = 10; cm < top; cm += 10) {
    const len = cm % 50 ? 4 : 8;
    o += qU(u - 2.6, v0, v0 + len, cm - 0.7, cm + 0.7, "sc-tick");
  }
  const fs = Math.max(12 * k, 12);
  for (let i = 0; i < 5; i++) {
    const zc = i === 0 ? 72 : ((bounds[i] ?? 0) + (bounds[i + 1] ?? 0)) / 2;
    if (zc - 5 < cut.clip) continue;
    const [x, y] = pt(u - 2.6, (v0 + v1) / 2 + 2, zc);
    o += `<text class="sc-num ${i < 2 ? "sc-num-dark" : "sc-num-light"}" font-size="${f1(fs)}" transform="matrix(${f1(CB * 1000) / 1000} ${f1(SB * 1000) / 1000} 0 1 ${f1(x)} ${f1(y)})">${i + 1}</text>`;
  }
  return o;
}

/** Mobile barriers: red ribbed modules rising from the yard as `raised` goes 0 → 1, else a stack at the house. */
export function barriers(raised: number): string {
  let o = "";
  const W = LV / 5;
  const n = 5;
  const Y = LEVELS.wall;
  const H = LEVELS.barrierTop - Y;
  if (raised < 1) {
    o += `<g opacity="${op(1 - raised)}">`;
    for (let i = 0; i < 4; i++) {
      const u1 = HOUSE.u0 - 1 - i * 7;
      o += box(u1 - 6, u1, 76, 108, Y, Y + 46 - i * 2, "sc-bar");
    }
    o += "</g>";
  }
  if (raised <= 0) return o;
  o += qT(Y, BAR_U - 3, BAR_U + 22, 0, LV, "sc-shadow");
  for (let i = n - 1; i >= 0; i--) {
    const t = Math.min(1, Math.max(0, raised * 1.6 - (0.6 * i) / n));
    if (t <= 0) continue;
    const h = H * (1 - (1 - t) ** 3);
    const z1 = Y + h;
    // stepped profile like the real modules: a deep foot, a slimmer upper part, ribs on the dry side
    const u0 = BAR_U;
    const v0 = i * W + 1.5;
    const v1 = (i + 1) * W - 1.5;
    const zm = Y + h * 0.3;
    o += box(u0, u0 + 18, v0, v1, Y, zm, "sc-bar");
    o += box(u0 + 5, u0 + 13, v0, v1, zm, z1, "sc-bar");
    o += qU(u0 + 4.8, v0, v1, Y + h * 0.62, Y + h * 0.66, "sc-rib");
  }
  return o;
}

/** A low wall of sandbags around the house front, five rows from the yard to the house floor, laid row by row. */
export function sandbags(laid: number): string {
  if (laid <= 0) return "";
  const Y = LEVELS.wall;
  const rows = 5;
  const hgt = (LEVELS.bagTop - Y) / rows;
  const L = 18;
  let o = qT(Y, BAGS.u0 - 4, BAGS.u1 + 4, BAGS.v0 - 4, LV, "sc-shadow");
  for (let r = 0; r < rows; r++) {
    const t = Math.min(1, Math.max(0, laid * rows - r));
    if (t <= 0) break;
    const z0 = Y + r * hgt + (1 - t) * 14;
    const z1 = z0 + hgt - 0.8;
    const inset = r * 0.8;
    const off = r % 2 ? L / 2 : 0;
    let row = "";
    // side run along the facade, back to front
    for (let v = LV - off; v > BAGS.v0 + 16; v -= L)
      row += box(
        BAGS.u0 + inset,
        BAGS.u1 - inset,
        Math.max(BAGS.v0 + 16, v - L) + 0.8,
        v - 0.6,
        z0,
        z1,
        "sc-bag",
      );
    // front run across to the block edge, far to near
    for (let u = UMAX - off; u > BAGS.u0; u -= L)
      row += box(
        Math.max(BAGS.u0, u - L) + 0.6 + (u - L <= BAGS.u0 ? inset : 0),
        u - 0.6,
        BAGS.v0 + inset,
        BAGS.v0 + 16 - inset,
        z0,
        z1,
        "sc-bag",
      );
    o += `<g opacity="${op(t)}">${row}</g>`;
  }
  return o;
}

export function tree(
  u: number,
  v: number,
  z0: number,
  h: number,
  r: number,
): string {
  const [x, y] = pt(u, v, z0 + h + r * 0.85);
  let o = qT(z0, u - 2, u + 26, v - 6, v + 24, "sc-shadow");
  o += box(u - 3, u + 3, v - 3, v + 3, z0, z0 + h + 4, "sc-trunk");
  if (z0 + h + r * 1.8 < cut.clip) return o;
  o += `<circle class="sc-tree-m" cx="${f1(x)}" cy="${f1(y)}" r="${r}"/>`;
  o += `<path class="sc-tree-d" d="M${f1(x - r)},${f1(y)}A${r},${r} 0 0 0 ${f1(x + r)},${f1(y)}A${r * 1.15},${r * 0.75} 0 0 1 ${f1(x - r)},${f1(y)}Z"/>`;
  o += `<circle class="sc-tree-l" cx="${f1(x - r * 0.3)}" cy="${f1(y - r * 0.32)}" r="${f1(r * 0.5)}"/>`;
  return o;
}

/** A parked car, cut off at the water surface when flooded. */
export function car(u0: number, v0: number, v1: number, m: string): string {
  const Pz = LEVELS.park;
  const u1 = u0 + 128;
  let o =
    cut.clip <= Pz ? qT(Pz, u0 - 3, u1 + 12, v0 - 2, v1 + 8, "sc-shadow") : "";
  o += box(u0, u1, v0, v1, Pz + 12, Pz + 56, m);
  o += box(u0 + 24, u1 - 30, v0 + 4, v1 - 4, Pz + 56, Pz + 96, m);
  o +=
    qV(v0 + 3.7, u0 + 30, u1 - 36, Pz + 61, Pz + 90, "sc-glass") +
    qV(v0 + 3.5, u0 + 60, u0 + 64, Pz + 61, Pz + 90, `${m}-f`);
  o += qU(u0 + 23.7, v0 + 8, v1 - 8, Pz + 61, Pz + 90, "sc-glass");
  o +=
    qU(u0 - 0.3, v0 + 3, v0 + 12, Pz + 42, Pz + 50, "sc-tail") +
    qU(u0 - 0.3, v1 - 12, v1 - 3, Pz + 42, Pz + 50, "sc-tail");
  o +=
    ringV(v0 - 0.4, u0 + 26, Pz + 16, 13, 16, "sc-tyre") +
    ringV(v0 - 0.4, u1 - 24, Pz + 16, 13, 16, "sc-tyre");
  return o;
}

export function parkSign(): string {
  const u = 226;
  const v = 14;
  const Pz = LEVELS.park;
  let o = box(u - 2, u + 2, v - 2, v + 2, Pz + 5, Pz + 128, "sc-pole");
  o +=
    qU(u - 19, v - 5, v - 3, Pz + 88, Pz + 128, "sc-sign-edge") +
    qT(Pz + 128, u - 19, u + 19, v - 5, v - 3, "sc-sign-edge");
  o += qV(v - 5, u - 19, u + 19, Pz + 88, Pz + 128, "sc-sign");
  if (cut.clip < Pz + 120) {
    const [x, y] = pt(u, v - 5.5, Pz + 97);
    o += `<text class="sc-p" font-size="30" transform="matrix(${f1(CA * 1000) / 1000} ${-f1(SA * 1000) / 1000} 0 1 ${f1(x)} ${f1(y)})">P</text>`;
  }
  return o;
}

/** The forecast range on the staff and the label tag at the waterline (its text is set by the engine). */
export function rangeAndTag(
  L: number,
  range: readonly [number, number] | null,
  k: number,
  clearSign = false,
): string {
  let o = "";
  if (range) {
    const lo = Math.max(0, Math.min(...range));
    const hi = Math.min(STAFF.top, Math.max(...range));
    const u = STAFF.u - 3;
    o += path(
      [
        [u, STAFF.v0 - 5, lo],
        [u, STAFF.v1 + 5, lo],
        [u, STAFF.v1 + 5, hi],
        [u, STAFF.v0 - 5, hi],
      ],
      "sc-range",
    );
  }
  const fs = 13 * k;
  const hgt = fs * 1.9;
  const [ax, ay] = pt(STAFF.u - 3, STAFF.v1, Math.max(L, 0));
  // Beside the staff over the river; when the water nears the top, above the staff with a leader down to it.
  const staffTop = pt(STAFF.u, STAFF.v1, STAFF.top)[1];
  let cy = Math.max(staffTop + hgt, ay - hgt * 0.9);
  // In the narrow view the tag reaches over the P sign; lift it above the sign, the leader shows the level.
  if (clearSign) cy = Math.min(cy, pt(226, 14, LEVELS.park + 128)[1] - hgt);
  const lx = ax - 14 * k;
  o += `<g class="sc-tag"><path class="sc-tag-lead" d="M${f1(lx)},${f1(cy)}L${f1(ax)},${f1(ay)}"/><circle class="sc-tag-dot" cx="${f1(ax)}" cy="${f1(ay)}" r="${f1(2.2 * k)}"/>`;
  o += `<rect class="sc-tag-box" y="${f1(cy - hgt / 2)}" height="${f1(hgt)}" rx="${f1(hgt / 2)}"/><text class="sc-tag-text" y="${f1(cy)}" font-size="${f1(fs)}" data-right="${f1(lx)}"></text></g>`;
  return o;
}
