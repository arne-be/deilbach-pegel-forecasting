// The page's one island: loads forecast and history, keeps the freshness current and passes the
// hour picked in the chart on to the scene.
import { type ReactNode, useCallback, useEffect, useState } from "react";
import type { FixtureName } from "../fixtures";
import {
  categoryFor,
  categoryTags,
  levelAt,
  type State,
  stateOf,
  verdict,
} from "../lib/forecast";
import {
  berlinClock,
  berlinDayWord,
  berlinHourPhrase,
  formatCm,
} from "../lib/format";
import type {
  ForecastResponse,
  HistoryPoint,
  HistoryResponse,
} from "../lib/types";
import CategoryCards from "./CategoryCards";
import ForecastChart from "./ForecastChart";
import LevelNow from "./LevelNow";
import SiteScene from "./SiteScene";
import Verdict, { PORTAL_URL } from "./Verdict";
import "./ForecastApp.css";

const REFETCH_MS = 5 * 60_000;
const RECHECK_MS = 60_000;

interface Data {
  forecast: ForecastResponse;
  history: HistoryPoint[];
}

/** A fixed case for screenshots and checks: data, the time it is viewed at and a picked hour. */
interface Pinned extends Data {
  nowMs: number;
  hoverMs: number | null;
}

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json() as Promise<T>;
}

async function fetchData(): Promise<Data> {
  const [forecast, history] = await Promise.all([
    getJson<ForecastResponse>("/api/forecast"),
    getJson<HistoryResponse>("/api/history"),
  ]);
  if (!Array.isArray(forecast.points) || !Array.isArray(history.observations)) {
    throw new Error("unexpected API response");
  }
  return { forecast, history: history.observations };
}

/** `?fixture=flood[&hover=2026-11-19T22:22Z]`; never the default, only when asked for. */
async function pinnedFromQuery(search: string): Promise<Pinned | null> {
  const query = new URLSearchParams(search);
  const name = query.get("fixture");
  if (!name) return null;
  // A separate chunk, so the normal page never downloads the fixtures.
  const { fixtures } = await import("../fixtures");
  if (!(name in fixtures)) return null;
  const fixture = fixtures[name as FixtureName];
  const hover = Date.parse(query.get("hover") ?? "");
  return {
    forecast: fixture.forecast,
    history: fixture.history.observations,
    nowMs: Date.parse(fixture.now),
    hoverMs: Number.isNaN(hover) ? null : hover,
  };
}

/** "16:22 Uhr" today, else with the day: "gestern 23:22 Uhr". */
function readingText(ms: number, nowMs: number): string {
  const day = berlinDayWord(ms, nowMs);
  return day === "heute" ? berlinClock(ms) : `${day} ${berlinClock(ms)}`;
}

/** The scene's tag: "23 Uhr · 172 cm" today, "morgen 3 Uhr · 150 cm" on other days. */
function sceneLabel(ms: number, levelCm: number, nowMs: number): string {
  const hour = berlinHourPhrase(ms, nowMs).replace(/^heute /, "");
  return `${hour} · ${formatCm(levelCm)}`;
}

/** "Keine amtliche Warnung", with the portal link unless the badge above already carries it. */
function LegalLine({ portal }: { portal: boolean }) {
  return (
    <p className="legal">
      Keine amtliche Warnung
      {portal && (
        <>
          <span className="sep"> ·</span>{" "}
          <a href={PORTAL_URL}>Hochwasserportal NRW</a>
        </>
      )}
    </p>
  );
}

/** `children` are the static sections ("So entsteht die Vorhersage", "Warum diese Vorhersage?"), placed above the legal line. */
export default function ForecastApp({ children }: { children?: ReactNode }) {
  const [data, setData] = useState<Data | null>(null);
  const [failed, setFailed] = useState(false);
  const [pinned, setPinned] = useState<Pinned | null>(null);
  const [clockMs, setClockMs] = useState(() => Date.now());
  const [hoverMs, setHoverMs] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Only the newest request may set the data, so a slow older answer can't overwrite a newer one.
    let latestRequest = 0;
    const timers: number[] = [];
    const refresh = () => {
      const request = ++latestRequest;
      return fetchData().then(
        (next) => {
          if (cancelled || request !== latestRequest) return;
          setData(next);
          setFailed(false);
        },
        (error: unknown) => {
          console.error("Pegel data failed to load", error);
          // Data already shown stays: stateOf turns it stale once it is too old.
          if (!cancelled && request === latestRequest) setFailed(true);
        },
      );
    };
    const onVisible = () => {
      if (document.hidden) return;
      setClockMs(Date.now());
      refresh();
    };
    pinnedFromQuery(location.search)
      .catch((error: unknown) => {
        console.error("Fixture failed to load", error);
        return null;
      })
      .then((found) => {
        if (cancelled) return;
        if (found) {
          setPinned(found);
          setHoverMs(found.hoverMs);
          return;
        }
        refresh();
        timers.push(window.setInterval(refresh, REFETCH_MS));
        timers.push(
          window.setInterval(() => setClockMs(Date.now()), RECHECK_MS),
        );
        document.addEventListener("visibilitychange", onVisible);
      });
    return () => {
      cancelled = true;
      for (const timer of timers) clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  const onHover = useCallback((ms: number | null) => setHoverMs(ms), []);

  const shown = pinned ?? data;
  // Fixtures work in production builds too (for screenshots), so they say so on the page.
  const testNotice = pinned && (
    <p className="testdata" role="note">
      Testdaten, nicht der aktuelle Pegel
    </p>
  );
  const nowMs = pinned?.nowMs ?? clockMs;
  const latest = shown?.history.at(-1);

  const page = (main: ReactNode, portal: boolean) => (
    <>
      {main}
      {children}
      <LegalLine portal={portal} />
    </>
  );

  if (!shown && !failed) return page(<Skeleton />, true);
  // No data, or history without a single reading (ingest down longer than its window).
  if (!shown || !latest) {
    return page(
      <>
        <div className="hero">
          <Verdict
            state="error"
            verdict={null}
            current={null}
            reading={null}
            nowMs={nowMs}
          />
        </div>
        <CategoryCards tags={null} outlineCurrent={false} nowMs={nowMs} />
      </>,
      false,
    );
  }

  const { forecast, history } = shown;
  const latestMs = Date.parse(latest.observed_at);
  const state: State = stateOf(forecast, nowMs, latestMs);
  const fresh = state === "fresh";
  const points = fresh ? forecast.points : null;
  const reading = readingText(latestMs, nowMs);
  // A picked forecast hour is dropped once the forecast is no longer shown, so the scene never
  // labels an old reading with a future time.
  const lastMs = points?.length
    ? Date.parse(points[points.length - 1].valid_at)
    : latestMs;
  const hovered =
    hoverMs === null || hoverMs > lastMs
      ? null
      : levelAt(history, points, hoverMs);
  const sceneMs = hovered && hoverMs !== null ? hoverMs : latestMs;
  const sceneLevel = hovered?.levelCm ?? latest.level_cm;

  return page(
    <>
      {testNotice}
      <div className={state === "stale" ? "hero is-old" : "hero"}>
        <Verdict
          state={state}
          verdict={fresh ? verdict(forecast, latest.level_cm, nowMs) : null}
          current={categoryFor(latest.level_cm)}
          reading={reading}
          nowMs={nowMs}
        />
        <LevelNow levelCm={latest.level_cm} reading={reading} state={state} />
      </div>
      <div className="stage">
        <SiteScene
          levelCm={sceneLevel}
          label={sceneLabel(sceneMs, sceneLevel, nowMs)}
          range={hovered && !hovered.measured ? hovered.band90 : null}
          stale={state === "stale"}
        />
        <ForecastChart
          history={history}
          points={points}
          state={state}
          nowMs={nowMs}
          onHover={onHover}
          initialHoverMs={pinned?.hoverMs}
        />
      </div>
      <CategoryCards
        tags={categoryTags(forecast, latest.level_cm, state)}
        outlineCurrent={state !== "stale"}
        nowMs={nowMs}
      />
    </>,
    fresh,
  );
}

/** While loading: quiet shapes, never a number. */
function Skeleton() {
  return (
    <div className="skeleton" role="status" aria-busy="true" aria-label="Lädt">
      <div className="hero">
        <span className="bone line-a" />
        <span className="bone line-b" />
      </div>
      <div className="stage">
        <div className="card bone scene-box" />
        <div className="card bone chart-box" />
      </div>
    </div>
  );
}
