// The house beside the yard: plinth, facade, windows, door with steps, roof and chimney.
import {
  box,
  DOOR,
  HOUSE,
  LEVELS,
  LV,
  path,
  qT,
  qU,
  qV,
  UMAX,
} from "./geometry";

export function house(): string {
  const { u0, v0, eave, ridge, ridgeU } = HOUSE;
  const F = LEVELS.floor;
  const Y = LEVELS.wall;
  const slope = (ridge - eave) / (ridgeU - u0);
  let o = qT(Y, u0 - 6, UMAX, v0 - 6, LV, "sc-shadow");
  o += box(u0, UMAX, v0, LV, Y, F, "sc-plinth");
  o += qU(u0, v0, LV, F, eave, "sc-house-l");
  o += path(
    [
      [u0, v0, F],
      [UMAX, v0, F],
      [UMAX, v0, eave],
      [ridgeU, v0, ridge],
      [u0, v0, eave],
    ],
    "sc-house-f",
  );
  // windows on the facade (two storeys) and on the gable end
  const win = (v: number, z0: number, z1: number, w = 30) =>
    qU(u0 - 0.3, v - 2, v + w + 2, z0 - 3, z1 + 3, "sc-frame") +
    qU(u0 - 0.5, v, v + w, z0, z1, "sc-win") +
    qU(u0 - 0.7, v + w / 2 - 0.8, v + w / 2 + 0.8, z0, z1, "sc-frame") +
    box(u0 - 5, u0, v - 3, v + w + 3, z0 - 5, z0 - 2, "sc-con");
  for (const v of [116, 214]) o += win(v, F + 24, F + 76);
  for (const v of [92, 132, 172, 214]) o += win(v, F + 120, F + 172, 28);
  const gwin = (u: number, z0: number, z1: number) =>
    qV(v0 - 0.3, u - 2, u + 28, z0 - 3, z1 + 3, "sc-frame") +
    qV(v0 - 0.5, u, u + 26, z0, z1, "sc-win") +
    qV(v0 - 0.7, u + 12.2, u + 13.8, z0, z1, "sc-frame");
  o +=
    gwin(668, F + 24, F + 76) +
    gwin(740, F + 24, F + 76) +
    gwin(668, F + 120, F + 172) +
    gwin(740, F + 120, F + 172) +
    gwin(708, eave + 12, eave + 36);
  // door with steps up from the yard to the floor
  o +=
    qU(u0 - 0.3, DOOR.v0 - 3, DOOR.v1 + 3, F, F + 88, "sc-frame") +
    qU(u0 - 0.5, DOOR.v0, DOOR.v1, F, F + 85, "sc-door");
  o += qU(u0 - 0.7, DOOR.v0 + 4, DOOR.v0 + 7, F + 44, F + 52, "sc-frame");
  for (let i = 0; i < 3; i++)
    o += box(
      u0 - 9 * (3 - i),
      u0,
      DOOR.v0 - 6,
      DOOR.v1 + 6,
      Y,
      Y + ((F - Y) * (i + 1)) / 3,
      "sc-con",
    );
  // roof: the river-facing plane, the gable fascia and a chimney
  const eu = u0 - 10;
  const ez = eave - 10 * slope;
  const ru = 2 * ridgeU - eu;
  o += path(
    [
      [ru, v0 - 8, ez],
      [ru, LV, ez],
      [ridgeU, LV, ridge],
      [ridgeU, v0 - 8, ridge],
    ],
    "sc-roof-t",
  );
  o += path(
    [
      [eu, v0 - 8, ez],
      [eu, LV, ez],
      [ridgeU, LV, ridge],
      [ridgeU, v0 - 8, ridge],
    ],
    "sc-roof-l",
  );
  o += qU(eu, v0 - 8, LV, ez - 6, ez, "sc-roof-f");
  o += path(
    [
      [eu, v0 - 8, ez - 6],
      [eu, v0 - 8, ez],
      [ridgeU, v0 - 8, ridge],
      [ru, v0 - 8, ez],
      [ru, v0 - 8, ez - 6],
      [ridgeU, v0 - 8, ridge - 6],
    ],
    "sc-roof-f",
  );
  o += path(
    [
      [ridgeU - 2, v0 - 8, ridge + 1],
      [ridgeU - 2, LV, ridge + 1],
      [ridgeU + 1, LV, ridge],
      [ridgeU + 1, v0 - 8, ridge],
    ],
    "sc-ridge",
  );
  const cz = eave + (690 - u0) * slope;
  o += box(684, 700, 196, 212, cz - 4, ridge + 30, "sc-plinth");
  return o;
}
