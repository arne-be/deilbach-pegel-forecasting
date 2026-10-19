// Draws the scene into an <svg> and animates level, barrier, sandbag and skip changes.
// Ripples are a CSS animation; the requestAnimationFrame loop only runs while something changes.
import { categories } from "../../lib/config";
import {
  BOTTOM,
  cut,
  f1,
  LEVELS,
  LV,
  pt,
  THRESHOLDS,
  UMAX,
  VB_NARROW,
  VB_WIDE,
} from "./geometry";
import { house } from "./house";
import {
  barriers,
  car,
  carPark,
  frontSection,
  parkSign,
  rangeAndTag,
  sandbags,
  staff,
  terrainBack,
  tree,
} from "./site";
import { container, SKIP_U, water } from "./water";

const LEVEL_MS = 170; // level changes from the chart follow the pointer quickly
const BARRIER_MS = 700;
const SANDBAG_MS = 450;
// Drift: from upstream (back) to downstream (front) in 7 s, hidden for 3 s, then again; bobbing on the way.
const SKIP_PERIOD = 10000;
const SKIP_TRAVEL = 7000;
const WHAT = [
  "Das Wasser bleibt im Bachbett.",
  "Das Wasser steigt, bleibt aber im Bachbett.",
  "Der Parkplatz ist überschwemmt, die mobilen Barrieren stehen, Sandsäcke liegen um das Haus.",
  "Das Wasser geht über die Mauer, die Barrieren halten es.",
  "Das Wasser geht über die Barrieren und steht am Haus.",
];

const categoryIndex = (L: number): number =>
  THRESHOLDS.filter((t) => L > t).length;
const easeInOut = (p: number): number =>
  p < 0.5 ? 4 * p * p * p : 1 - (-2 * p + 2) ** 3 / 2;

const MAX_HEIGHT_PX = 520; // as in SiteScene.css

export class SceneEngine {
  private readonly staticLayer: SVGGElement;
  private readonly dynLayer: SVGGElement;
  private readonly reduce = matchMedia("(prefers-reduced-motion: reduce)");
  private readonly resize = new ResizeObserver(() => this.layout());
  private shown = 0;
  private placed = false;
  private anim: { from: number; to: number; t0: number | null } | null = null;
  private label = "";
  private range: [number, number] | null = null;
  private stale = false;
  private barT = 0;
  private bagT = 0;
  private raf = 0;
  private lastTs = 0;
  private narrow: boolean | null = null;
  private k = 1;
  private skip: SVGGElement | null = null;
  private skipT0: number | null = null;
  private readonly kick = () => {
    if (!this.raf) this.raf = requestAnimationFrame(this.frame);
  };

  private readonly svg: SVGSVGElement;

  constructor(svg: SVGSVGElement) {
    this.svg = svg;
    const layer = (cls: string) => {
      const g = svg.querySelector<SVGGElement>(cls);
      if (!g) throw new Error(`SiteScene: missing ${cls}`);
      return g;
    };
    this.staticLayer = layer(".sc-static");
    this.dynLayer = layer(".sc-dyn");
    this.resize.observe(svg);
    document.addEventListener("visibilitychange", this.kick);
    this.reduce.addEventListener("change", this.kick);
  }

  destroy(): void {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.resize.disconnect();
    document.removeEventListener("visibilitychange", this.kick);
    this.reduce.removeEventListener("change", this.kick);
  }

  /** Eases to the level in LEVEL_MS; the first call jumps there with barriers and sandbags already in place. */
  setLevel(cm: number, label: string, range: [number, number] | null): void {
    if (!Number.isFinite(cm)) return; // a NaN would blank every path; keep the last good picture
    const to = Math.max(0, cm);
    const instant = !this.placed;
    this.placed = true;
    this.label = label || `${Math.round(to)} cm`;
    this.range = range;
    this.anim = { from: instant ? to : this.shown, to, t0: null };
    if (instant) {
      this.shown = to;
      this.barT = this.barrierGoal(to);
      this.bagT = this.sandbagGoal(to);
    }
    if (this.narrow === null) this.layout();
    this.kick();
  }

  setStale(stale: boolean): void {
    this.stale = stale;
    if (this.narrow !== null) this.build();
    this.kick();
  }

  private barrierGoal = (L: number) => (L > LEVELS.barriersUp ? 1 : 0);
  private sandbagGoal = (L: number) => (L > LEVELS.sandbags ? 1 : 0);
  private rippling = () =>
    !this.stale && !this.reduce.matches && !document.hidden && this.shown > 0.5;

  private approach(
    value: number,
    goal: number,
    dt: number,
    ms: number,
  ): number {
    if (this.reduce.matches) return goal;
    const step = dt / ms;
    return goal > value
      ? Math.min(goal, value + step)
      : Math.max(goal, value - step);
  }

  private readonly frame = (ts: number): void => {
    this.raf = 0;
    const dt = this.lastTs ? Math.min(1000, ts - this.lastTs) : 16;
    this.lastTs = ts;
    let dirty = false;
    if (this.anim) {
      this.anim.t0 ??= ts;
      const p = this.reduce.matches
        ? 1
        : Math.min(1, (ts - this.anim.t0) / LEVEL_MS);
      this.shown =
        this.anim.from + (this.anim.to - this.anim.from) * easeInOut(p);
      if (p >= 1) this.anim = null;
      dirty = true;
    }
    const bGoal = this.barrierGoal(this.shown);
    const sGoal = this.sandbagGoal(this.shown);
    if (this.barT !== bGoal) {
      this.barT = this.approach(this.barT, bGoal, dt, BARRIER_MS);
      dirty = true;
    }
    if (this.bagT !== sGoal) {
      this.bagT = this.approach(this.bagT, sGoal, dt, SANDBAG_MS);
      dirty = true;
    }
    if (dirty) this.build();
    else this.placeSkip(ts);
    if (
      this.anim ||
      this.barT !== bGoal ||
      this.bagT !== sGoal ||
      (this.skip && this.rippling())
    )
      this.kick();
    else this.lastTs = 0;
  };

  private layout(): void {
    const w = this.svg.clientWidth || 800;
    const isNarrow = w < 500;
    const vb = isNarrow ? VB_NARROW : VB_WIDE;
    const [, , vbW = 1, vbH = 1] = vb;
    // The CSS caps the height; then the height sets the scale (text sizes follow k).
    const nk = Math.max(
      vbW / w,
      vbH / Math.min(MAX_HEIGHT_PX, (w * vbH) / vbW),
    );
    if (isNarrow === this.narrow && Math.abs(nk - this.k) < 0.02) return;
    this.narrow = isNarrow;
    this.k = nk;
    this.svg.setAttribute("viewBox", vb.join(" "));
    this.buildStatic();
    this.build();
  }

  // ---- compose in painter's order: far (large u) to near, water between what it covers and what covers it ----
  // Everything that never changes with the level is built once per layout; build() redraws only the rest.
  private buildStatic(): void {
    cut.clip = Number.NEGATIVE_INFINITY;
    const s = [
      pt(0, 0, BOTTOM),
      pt(UMAX, 0, BOTTOM),
      pt(UMAX, LV, BOTTOM),
      pt(0, LV, BOTTOM),
    ];
    let o = `<path class="sc-block-shadow" filter="url(#sc-blur)" d="M${s.map((p) => `${f1(p[0] + 6)},${f1(p[1] + 14)}`).join("L")}Z"/>`;
    o +=
      terrainBack(this.k) +
      frontSection() +
      house() +
      tree(560, 236, LEVELS.wall, 70, 30);
    this.staticLayer.innerHTML = o;
  }

  private build(): void {
    const L = this.shown;
    cut.clip = Number.NEGATIVE_INFINITY;
    let o = sandbags(this.bagT) + barriers(this.barT);
    const parkUnder = L > LEVELS.park;
    const parked = () =>
      car(60, 176, 230, "sc-car2") + car(60, 22, 76, "sc-car3") + parkSign();
    if (parkUnder) o += carPark() + parked();
    o += water(L, this.stale);
    if (!parkUnder) o += carPark();
    cut.clip = L;
    o += staff(this.k); // the part above the surface sits in front of the water behind it
    o += L > LEVELS.floor ? container(L) : "";
    cut.clip = L > LEVELS.park ? L : Number.NEGATIVE_INFINITY;
    o +=
      tree(150, 244, LEVELS.park, 96, 36) +
      tree(30, 236, LEVELS.park, 74, 32) +
      tree(90, 246, LEVELS.park, 120, 28);
    o += parked();
    cut.clip = Number.NEGATIVE_INFINITY;
    o += rangeAndTag(L, this.range, this.k, this.narrow === true);
    this.dynLayer.innerHTML = o;
    this.skip = this.dynLayer.querySelector<SVGGElement>(".sc-skip");
    if (!this.skip) this.skipT0 = null;
    this.sizeTag();
    this.placeSkip(this.lastTs || performance.now());
    const n = categoryIndex(L);
    const name = categories[n]?.name ?? "";
    this.svg.setAttribute(
      "aria-label",
      `Schaubild Pegel Kupferdreh: ${this.label || `${Math.round(L)} cm`}, Kategorie ${n + 1} (${name}). ${WHAT[n] ?? ""}${this.stale ? " Die Daten sind veraltet." : ""}`,
    );
  }

  /** The label goes in as text content (never markup); the pill is sized to the rendered text. */
  private sizeTag(): void {
    const text = this.dynLayer.querySelector<SVGTextElement>(".sc-tag-text");
    const pill = this.dynLayer.querySelector(".sc-tag-box");
    if (!text || !pill) return;
    text.textContent = this.label;
    const w =
      (text.getComputedTextLength() || this.label.length * 7 * this.k) +
      24 * this.k;
    const right = Number(text.dataset.right);
    pill.setAttribute("x", String(f1(right - w)));
    pill.setAttribute("width", String(f1(w)));
    text.setAttribute("x", String(f1(right - w / 2)));
  }

  private placeSkip(ts: number): void {
    if (!this.skip) return;
    const moving = this.rippling();
    this.skipT0 ??= ts; // each appearance starts upstream
    const ph = moving ? ((ts - this.skipT0) % SKIP_PERIOD) / SKIP_TRAVEL : 0.5;
    const v = LV + 70 - ph * (LV + 140);
    const t = ts / 1000;
    const fade = ph > 1 ? 0 : Math.min(1, (LV + 50 - v) / 40, (v + 50) / 40);
    const [dx, dy] = pt(0, v, 0);
    const [cx, cy] = pt(SKIP_U, 0, this.shown);
    const bob = moving ? Math.sin(t * 2.3) * 2.2 : 0;
    const rot = moving ? Math.sin(t * 1.4) * 3.5 - 2 : -2;
    this.skip.setAttribute(
      "transform",
      `translate(${f1(dx)} ${f1(dy + bob)}) rotate(${f1(rot)} ${f1(cx)} ${f1(cy)})`,
    );
    this.skip.setAttribute(
      "opacity",
      String(f1(Math.max(0, fade) * 100) / 100),
    );
    // The tag steps back while the skip passes underneath it.
    const tag = this.dynLayer.querySelector(".sc-tag");
    if (!tag) return;
    const a = this.skip.getBoundingClientRect();
    const b = tag.getBoundingClientRect();
    const hit =
      fade > 0.2 &&
      a.left < b.right &&
      b.left < a.right &&
      a.top < b.bottom &&
      b.top < a.bottom;
    tag.classList.toggle("sc-behind", hit);
  }
}
