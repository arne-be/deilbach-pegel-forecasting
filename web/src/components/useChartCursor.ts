// Picking an hour in the chart with mouse, touch or keys. Mouse follows on hover. Touch follows from
// the first sideways move, so a vertical swipe scrolls the page; a tap picks one hour. The picked
// hour holds 1.5 s after the finger lifts.
import {
  type KeyboardEvent,
  type PointerEvent,
  useEffect,
  useRef,
  useState,
} from "react";

const HOLD_MS = 1500;

interface Timed {
  ms: number;
}

export function nearestIndex(samples: Timed[], ms: number): number {
  let best = 0;
  samples.forEach((s, i) => {
    if (Math.abs(s.ms - ms) < Math.abs(samples[best].ms - ms)) best = i;
  });
  return best;
}

interface CursorOptions {
  /** Every hour that can be picked, oldest first. */
  series: Timed[];
  /** The index shown at rest: the newest reading. */
  homeIdx: number;
  /** The time under the pointer. */
  timeAt: (event: PointerEvent<HTMLDivElement>) => number;
  onHover: (timeMs: number | null) => void;
  initialHoverMs: number | null;
}

export function useChartCursor({
  series,
  homeIdx,
  timeAt,
  onHover,
  initialHoverMs,
}: CursorOptions) {
  const holdRef = useRef(0);
  const touchRef = useRef<{
    id: number;
    x: number;
    y: number;
    following: boolean;
  } | null>(null);
  // The picked hour as a time, so a refresh that slides the window keeps the same hour.
  const [pickedMs, setPickedMs] = useState<number | null>(initialHoverMs);
  useEffect(() => () => clearTimeout(holdRef.current), []);

  const shownIdx =
    pickedMs === null || series.length === 0
      ? homeIdx
      : nearestIndex(series, pickedMs);

  const pick = (idx: number) => {
    clearTimeout(holdRef.current);
    const clamped = Math.max(0, Math.min(series.length - 1, idx));
    if (series[clamped].ms === pickedMs) return;
    setPickedMs(series[clamped].ms);
    onHover(series[clamped].ms);
  };
  const release = () => {
    // No early return on "nothing picked": the hold timer runs a release from an older render.
    clearTimeout(holdRef.current);
    setPickedMs(null);
    onHover(null);
  };
  const holdThenRelease = () => {
    clearTimeout(holdRef.current);
    holdRef.current = window.setTimeout(release, HOLD_MS);
  };
  const pickAt = (event: PointerEvent<HTMLDivElement>) =>
    pick(nearestIndex(series, timeAt(event)));

  const handlers = {
    onPointerDown: (event: PointerEvent<HTMLDivElement>) => {
      if (event.pointerType === "mouse") return;
      touchRef.current = {
        id: event.pointerId,
        x: event.clientX,
        y: event.clientY,
        following: false,
      };
    },
    onPointerMove: (event: PointerEvent<HTMLDivElement>) => {
      if (event.pointerType === "mouse") return pickAt(event);
      const touch = touchRef.current;
      if (!touch || touch.id !== event.pointerId) return;
      if (!touch.following) {
        const dx = Math.abs(event.clientX - touch.x);
        const dy = Math.abs(event.clientY - touch.y);
        if (dy > 8 && dy > dx) {
          touchRef.current = null;
          return;
        }
        if (dx < 6) return;
        touch.following = true;
        event.currentTarget.setPointerCapture(event.pointerId);
      }
      pickAt(event);
    },
    onPointerUp: (event: PointerEvent<HTMLDivElement>) => {
      const touch = touchRef.current;
      if (!touch || touch.id !== event.pointerId) return;
      if (!touch.following) pickAt(event);
      touchRef.current = null;
      holdThenRelease();
    },
    onPointerCancel: () => {
      if (touchRef.current?.following) holdThenRelease();
      touchRef.current = null;
    },
    onPointerLeave: (event: PointerEvent<HTMLDivElement>) => {
      if (event.pointerType === "mouse") release();
    },
    onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => {
      const moves: Record<string, number> = {
        ArrowLeft: shownIdx - 1,
        ArrowRight: shownIdx + 1,
        Home: 0,
        End: series.length - 1,
      };
      if (event.key in moves) {
        event.preventDefault();
        pick(moves[event.key]);
      } else if (event.key === "Escape") release();
    },
    onBlur: release,
  };
  return { shownIdx, handlers };
}

/**
 * Glides the cursor line and dot to the target hour along the line. Set on the DOM, so a frame
 * costs no render; instant on the first draw and under reduced motion.
 */
export function useCursorGlide(
  target: { ms: number; cm: number } | undefined,
  cmAt: (ms: number) => number | undefined,
  x: (ms: number) => number,
  y: (cm: number) => number,
) {
  const lineRef = useRef<SVGLineElement>(null);
  const dotRef = useRef<SVGCircleElement>(null);
  const shownMsRef = useRef<number | null>(null);
  const targetMs = target?.ms;
  const targetCm = target?.cm;
  useEffect(() => {
    if (targetMs === undefined || targetCm === undefined) return;
    const draw = (ms: number) => {
      const cm = cmAt(ms) ?? targetCm;
      lineRef.current?.setAttribute("x1", String(x(ms)));
      lineRef.current?.setAttribute("x2", String(x(ms)));
      dotRef.current?.setAttribute("cx", String(x(ms)));
      dotRef.current?.setAttribute("cy", String(y(cm)));
    };
    const instant =
      matchMedia("(prefers-reduced-motion: reduce)").matches ||
      shownMsRef.current === null;
    if (instant) {
      shownMsRef.current = targetMs;
      draw(targetMs);
      return;
    }
    let raf = 0;
    let last = 0;
    const step = (ts: number) => {
      const dt = last ? Math.min(250, ts - last) : 16;
      last = ts;
      let shown = shownMsRef.current ?? targetMs;
      shown += (targetMs - shown) * (1 - Math.exp(-dt / 140));
      if (Math.abs(targetMs - shown) < 20e3) shown = targetMs;
      shownMsRef.current = shown;
      draw(shown);
      if (shown !== targetMs) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [targetMs, targetCm, cmAt, x, y]);
  return { lineRef, dotRef };
}
