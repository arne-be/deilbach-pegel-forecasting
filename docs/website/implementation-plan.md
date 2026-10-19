# Implementation plan: the forecast page

Turns [mockup-kombi.html](mockup-kombi.html) into the real page in `web/` (Astro, React, TypeScript), fed by the live API, and publishes it on `deilbach-pegel.energiekonzepte-ruhr.de`. Written for subagents: each work package lists the files it owns, what it gets from earlier packages and when it is done.

## What exists

- **Hosting.** `infra/prod/website.tf`: S3 + CloudFront on the subdomain. `/api/*` goes to the API Lambda (`infra/prod/api.tf`, #107); everything else to the site bucket. The deploy job (`.github/workflows/infra.yml`) runs `pnpm build` in `web/` and syncs `web/dist` to S3 on every merge to `main`, then invalidates CloudFront.
- **Site.** `web/` is a placeholder: Astro 7.3.8 with `output: "static"`, one page, no React yet. CI (`.github/workflows/web.yml`): `astro check`, `vitest run`, `biome check`, `build`.
- **API.** Same origin, so no CORS:
  - `GET /api/forecast` → `ForecastResponse` (`src/pegel/api/schemas.py`): `station_id`, `model`, `issued_at`, `newest_observation_at`, `situation`, `points[]` with `valid_at`, `level_cm`, `bands[]` (`coverage_percent` 80, 90, 95, `lower_cm`, `upper_cm`). 404 when there is no forecast.
  - `GET /api/history` → `HistoryResponse`: `station_id`, `from`, `to`, `observations[]` with `observed_at`, `level_cm`. Without parameters: the last 7 days (Europe/Berlin), served from `recent.json`.
  - Both come from S3 files written by the hourly run (#106), with Neon as fallback. CloudFront caches `/api/*` for up to 5 minutes and serves the last good answer for a day if the Lambda fails.
- **Config.** `config/pegel.json`: categories (`number`, `name`, `above_cm`), `freshness` (90 min for observation and forecast), `forecast.horizon_hours` (24), `bands.coverages_percent`.

## The real data (what the page must handle)

Taken from prod on 2026-10-16:

- **One reading an hour** at about :22, a new forecast at :30. So `newest_observation_at` is about 8 minutes before `issued_at`, and the page is fresh for 90 minutes after each.
- **24 forecast points,** hourly from one hour after the newest reading (`…:22`). The page uses the 80 and 90 % bands and ignores 95.
- **Low water most of the time:** 17–21 cm in October 2026, against thresholds from 145 cm. The record is 168 cm (19.11.2024); there's no category 4 or 5 in the data. The fixed 0–250 cm axis keeps that in perspective.
- **Gaps:** history has missing hours (e.g. 2026-10-15 15:22). Never draw a line across a gap longer than 2 hours.
- **Fallback:** when the model step fails, `model` is `persistence` and every point has empty `bands`: a flat line at the last level. The page treats this as "no forecast".
- **`situation`** (`calm`, `moving`, `strong`, `degraded`) fires `strong` for a rise from 19 to 31 cm. The page doesn't use it.
- **Times** are UTC ISO strings; display in Europe/Berlin with `Intl.DateTimeFormat("de-DE", { timeZone: "Europe/Berlin" })`.

Fixtures: save one real `/api/forecast` and `/api/history` response in `web/src/fixtures/` (from the live API, or from prod with a read-only query), plus the made-up `flood`, `stale`, `fallback` and `chaos` cases from the mockup. Tests use only these.

## Rules carried over from the mockup

- **Category** of a level: the highest category whose `above_cm` the level is *strictly above* (145,0 cm is category 1), as in `src/pegel/core/categories.py`.
- **Verdict:** the forecast line sets the expected category. When the 90 % upper bound reaches a higher one within 24 h, add "Möglich: …" with the dashed chip.
- **Times** for "erwartet gegen" and "möglich ab": the hour of the last forecast point *before* the line (or the 90 % top) crosses the threshold. Hour only ("gegen 21 Uhr"), with "morgen" or the weekday after midnight.
- **Stale:** `newest_observation_at` or `issued_at` older than `freshness.*_max_age_minutes`. **Fallback:** `model == "persistence"` or no point has bands. Either way: no verdict, no forecast in the chart or the scene, a badge "Veraltet · 16:22 Uhr" or "Keine Prognose · 16:22 Uhr" and the Hochwasserportal NRW link. The scene water turns grey and still only when stale. Check freshness every minute and on `visibilitychange`; refetch every 5 minutes.
- **API failure** (network error, 404, 5xx): show the same badge with "Keine Daten", never an old number as current. A failed refetch after a good load keeps the shown data; the timestamps turn it to "Veraltet" after 90 minutes anyway. The newest history reading counts too: if it's older than the observation limit, the page is stale even when the forecast is fresh (CloudFront can serve an old history file for a day).
- **Categories section:** current category outlined, "erwartet gegen …" / "möglich ab …" tags, grey cards for categories neither current nor reached within 24 h (all but the current one when stale or in fallback).

## Mobile first

Most visitors will open the page on a phone, often outdoors in the rain. Every package designs for 360–430 px first and widens from there:

- No horizontal scroll from 320 px up; content uses the full width with a 16 px gutter.
- Body text at least 16 px, nothing under 12 px; tap targets at least 44 × 44 px (menu, chart cursor, links, state badges).
- `<meta name="viewport" content="width=device-width, initial-scale=1">`, no zoom lock; `env(safe-area-inset-*)` padding for notches and the home bar.
- The scene uses its narrow viewBox below 500 px (car park, P sign, river, staff, barriers, house front); the chart keeps the 0–250 axis readable at 360 px.
- Touch on the chart starts only after a sideways move, so a vertical swipe scrolls the page.
- The header collapses to the logo, wordmark and a working hamburger menu, as on energiekonzepte-ruhr.de.
- Performance on a mid-range phone: first content within 2 s on a 4G connection, the animation at 60 fps with under 2 ms of script per frame, nothing animating in hidden tabs or under reduced motion.
- Check each package at 375 × 812 (iframe screenshots, since headless Chrome won't go below 500 px) and before publishing on a real iPhone (Safari) and a real Android phone (Chrome).

## Work packages

Run them in this order; 2, 3 and 4 in parallel, each in its own worktree stacked on the branch of package 1, as in earlier parallel work on this repo. Every package: Conventional Commit, PR with `--base` the package 1 branch, checks green (`pnpm astro check`, `pnpm vitest run`, `pnpm biome check .`, `pnpm build`; plus `uv run mypy src tests`, `uv run pytest` and ruff for package 1's config change), a review subagent that loads `ponytail:ponytail`, and no merge.

### 0 · Deploy the API route (owner: the user)

#107 merged at 13:20 UTC, but no `infra` run on `main` followed, and `/api/forecast` on the subdomain still returns S3's 403. Rerun the `infra` workflow on `main` (or push an empty change), then check `curl -s https://deilbach-pegel.energiekonzepte-ruhr.de/api/forecast` returns JSON. Without this, the page can't load data.

### 1 · Scaffold (one agent, first)

Owns: `web/package.json`, `web/pnpm-lock.yaml`, `web/astro.config.mjs`, `web/tsconfig.json`, `web/src/layouts/Base.astro`, `web/src/styles/global.css`, `web/src/lib/types.ts`, `web/src/lib/config.ts`, `web/src/fixtures/`, `config/pegel.json`, `src/pegel/config.py` (+ its test).

- Add `@astrojs/react`, `react`, `react-dom`, `@types/react`, `@types/react-dom` (React is already the agreed stack, docs/decisions); pin the versions that resolve.
- `astro.config.mjs`: the React integration, and a Vite dev proxy from `/api` to `http://localhost:8000` so `pnpm dev` talks to the local API.
- `types.ts`: TypeScript types mirroring `ForecastResponse` and `HistoryResponse` exactly (field names as in the JSON).
- `config/pegel.json`: give each category `description` and `actions` (the texts from the mockup's "Stufen und Maßnahmen"), and add `site.history_hours` (24) and `site.scale_top_cm` (250). Extend the Pydantic model in `src/pegel/config.py` so validation passes. `config.ts` imports the JSON at build time and exports categories, freshness and these values; nothing else hard-codes them.
- `Base.astro`: `<html lang="de">`, the header and footer copied from the mockup (they mirror energiekonzepte-ruhr.de, links absolute to the main site), `global.css` with the site's tokens. Copy the logos into `web/public/` instead of hotlinking them.
- **Self-host the fonts** (Space Grotesk and Manrope as `woff2` in `web/public/fonts/`, `@font-face` in `global.css`). Loading them from Google's servers sends visitors' IP addresses to Google, which German courts have ruled needs consent. With self-hosted fonts and no other third-party requests, the page sets no cookies and needs no consent banner.
- Fixtures as described above.

Done when: `pnpm dev` shows the header and footer with an empty main, the checks pass, and a `ForecastResponse` fixture type-checks against `types.ts`.

### 2 · Forecast logic (agent A, parallel)

Owns: `web/src/lib/forecast.ts`, `web/src/lib/format.ts`, `web/src/lib/forecast.test.ts`, `web/src/lib/format.test.ts`.

Port the mockup's compute functions as pure, typed functions: `categoryFor`, `freshness` (`fresh | stale | fallback | error`), `verdict` (expected, possible, times), `categoryTags`, `levelAt(time)` (interpolated, for the hover), `trend3h`, `distanceToCritical`, `berlinHour` and the "morgen"/weekday wording, German number formatting (`68,5 cm`). Tests with the fixtures: the numbers the mockup shows (flood: 146 cm by 3 h, peak 172 cm at 23 Uhr, Kat. 3 "gegen 21 Uhr", Kat. 4 "ab 21 Uhr"; normal: Kat. 1, no "möglich"), the 145,0 boundary, a missing hour, the 90-minute boundary on both timestamps, fallback detection.

### 3 · Chart (agent B, parallel)

Owns: `web/src/components/ForecastChart.tsx`, `web/src/components/ForecastChart.css`.

Port the mockup's chart to a React SVG component. Props: history, forecast points, state, `onHover(time | null)`. Fixed 0–250 cm axis (grows only if a value exceeds it), coloured zones with threshold labels in the right margin, 80/90 % shading, dashed forecast, "Jetzt" with the ↔ cue, measured line broken at gaps. Pointer, touch (only after a sideways move, so vertical scroll works) and keyboard (`role="slider"`, arrows, Escape); the touched hour holds 1.5 s. Responsive by container width. Uses only `forecast.ts` signatures from package 2 (agree on them from this plan; stub them until 2 lands).

### 4 · Scene (agent C, parallel)

Owns: `web/src/components/SiteScene.tsx`, `web/src/components/SiteScene.css`.

Port the mockup's isometric scene and its `Scene` engine to a React component. Props: `level`, `label`, `range`, `stale`. Keep the drawing and the thresholds from config: car park 165, wall 185, barriers up and sandbags out from 165 (category 3), both holding to 225, house at 225, brown water and the drifting skip above 225. One `requestAnimationFrame` loop in an effect, paused in hidden tabs, still under `prefers-reduced-motion`, cleaned up on unmount. The two viewBoxes (wide and narrow) switch by container width.

### 5 · Page (one agent, after 2–4)

Owns: `web/src/pages/index.astro`, `web/src/components/ForecastApp.tsx`, `Verdict.tsx`, `LevelNow.tsx`, `CategoryCards.tsx`, `web/src/components/HowItWorks.astro`.

- `ForecastApp` (one React island, `client:load`): fetches `/api/forecast` and `/api/history` (no parameters), refetches every 5 minutes, rechecks freshness every minute and on `visibilitychange`, and passes the hovered time from the chart to the scene.
- Order: title, verdict and level now, scene, chart, "Stufen und Maßnahmen", "So entsteht die Vorhersage", "Keine amtliche Warnung · Hochwasserportal NRW", footer.
- Loading: a quiet skeleton, never a number. `<noscript>`: one line with the portal link.
- Rebase packages 2–4 onto 1 as they land, and wire the real functions in.

Done when: the page runs against the fixtures and against the local API (`uv run uvicorn pegel.api.app:app` on the `dev` branch), and screenshots at 375 and 1280 px match the mockup in the states normal, flood, stale and fallback (fixtures served by a test flag such as `?fixture=flood`, stripped from production builds or harmless there).

### 6 · Review (two agents, after 5)

- A visual critic: the real page next to the mockup, all states, phone and desktop, light and dark; and the header/footer next to energiekonzepte-ruhr.de.
- A code review subagent with `ponytail:ponytail`: logic, freshness, error states, accessibility, bundle size (aim under 150 kB gzipped JS).
Fix the findings in the owning packages.

### 7 · Publish (the user)

Merge the stacked PRs into `main` one at a time, package 1 first (it changes `config/pegel.json` and the Python config, so the Python checks must pass too). The deploy job builds and syncs the site. Merges that deploy need your explicit "Merge PR #N into main".

After the deploy, verify on `https://deilbach-pegel.energiekonzepte-ruhr.de/`:
- `/api/forecast` and `/api/history` return JSON with a `newest_observation_at` from the last hour;
- the page shows today's level and the 24 h forecast, and switches to "Veraltet" when you fake the clock past 90 minutes (devtools);
- phone and desktop screenshots look like the mockup;
- the first hourly run after the deploy still writes `forecast.json` (Lambda log `/aws/lambda/deilbach-pegel-run-hourly`).

## Legal (the client decides)

The page is public and run for a business, so it needs an Impressum and a Datenschutzerklärung. The footer links to the main site's Impressum; energiekonzepte-ruhr.de has no Datenschutz page yet. Before publishing, the client should add one that also covers this subdomain (AWS CloudFront in Frankfurt as host, server logs, no cookies, no tracking), and the footer links to it.

## Out of scope for now

History beyond 24 h (a range picker), a 48 h horizon, push or email alerts, dark mode polish, a login. The API already supports longer history ranges, so a picker is a later small change.
