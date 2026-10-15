# AGENTS.md

Hourly 48-hour water level forecast for the Deilbach gauge at Kupferdreh, shown on a public German-language web page. See `README.md` for the flood categories and plan, and `docs/architecture.md` for how the parts fit together.

## What exists now

Everything else in this file is the agreed plan. Folders and commands become real as the code lands, so don't assume a command works until its folder exists. Add one line here per new component, so parallel PRs don't conflict.

- Python project: `pyproject.toml`, `uv.lock`, `mise.toml`, `config/pegel.json`, `src/pegel/config.py`
- Shared types: `src/pegel/core/observations.py`, `src/pegel/core/forecasts.py`
- Persistence baseline, flood categories, per-horizon summary: `src/pegel/core/persistence.py`, `categories.py`, `summary.py`
- Issue times and backfill windows: `src/pegel/core/schedule.py`
- InfluxDB source adapter: `src/pegel/adapters/sources/influx.py`
- JSON-lines logging: `src/pegel/adapters/logging.py`
- Database: `db/`, `src/pegel/adapters/storage/`, `scripts/refresh-schema.sh`, `scripts/generate_records.py`
- Local CLI `pegel` with `backfill` and `run-hourly`: `src/pegel/jobs/`
- AWS state bucket and GitHub OIDC roles: `infra/bootstrap/` (applied by hand once)
- Hourly job on Lambda: `Dockerfile` (jobs target), `src/pegel/jobs/lambda_handler.py`, `src/pegel/adapters/secrets.py`, `infra/prod/`, `.github/workflows/infra.yml`, `docs/setup-aws.md`
- API `GET /api/history` and `GET /api/forecast` (FastAPI): `src/pegel/api/`, `src/pegel/core/history.py`
- LANUV stations and value parser: `config/pegel.json`, `src/pegel/adapters/sources/lanuv.py`
- ICON-D2 rain forecast from Open-Meteo, hourly step and `backfill-forecast`: `src/pegel/adapters/sources/open_meteo.py`, `src/pegel/core/rain_forecast.py`, `src/pegel/jobs/rain_forecast.py`
- Hourly live ingest of the upstream LANUV gauges (failures logged, never block the forecast): `src/pegel/adapters/sources/lanuv.py` (`fetch_levels`), `src/pegel/jobs/pipeline.py`
- LANUV level history from open data CSV files (`pegel backfill --source lanuv-files`): `src/pegel/adapters/sources/lanuv_files.py`
- Live Kalman outlier filter for the forecast station's level (`kupferdreh:cleaned_kalman`, `pegel clean`): `src/pegel/core/cleaning.py`, `src/pegel/jobs/pipeline.py`
- Generic series tables (`series`, `observations`, `input_forecasts`): `src/pegel/core/series.py`, `src/pegel/adapters/storage/series.py`, `observations.py`, `input_forecasts.py`
- Catchment, zones and forecast ring: `config/catchment.geojson`, `scripts/build_catchment.py`, `docs/catchment.md`
- Rain config (`rain` in `config/pegel.json`, `config/radolan_cells.json`, `config/icon_d2_points.json`) and extra hourly steps: `src/pegel/config.py`, `src/pegel/jobs/pipeline.py`
- Radar rain (DWD RADOLAN RW): hourly step `radar_rain` and `pegel backfill-radar`: `src/pegel/adapters/sources/radolan.py`, `src/pegel/core/radar.py`, `src/pegel/jobs/radar.py`
- `scripts/influx-query.sh` and the docs
- Grafana Cloud dashboards as code (read-only role `pegel_grafana`): `grafana/dashboards/`, `infra/prod/grafana.tf`, `docs/setup-grafana.md`
- Live outlier filter exploration (three methods compared, plots, recommendation): `analysis/outliers/`
- Evaluation dataset as known at each issue time (`pegel build-eval-set`): `src/pegel/core/issue_inputs.py`, `src/pegel/jobs/eval_set.py`
- Model evaluation contracts (`evaluation` config, folds, dataset and file schemas, model interface): `src/pegel/evaluation/contract.py`, `tests/eval_factory.py`
- Evaluation harness, persistence model, model registry and runner (`python -m pegel.evaluation.predict <dataset> --out <dir>`, writes `predictions.parquet`): `src/pegel/evaluation/harness.py`, `registry.py`, `predict.py`, `models/`
- Model inputs shared by training and the live job: `src/pegel/core/features.py`
- Evaluation metrics, flood events and the scoring runner (`python -m pegel.evaluation.score`): `src/pegel/evaluation/metrics.py`, `events.py`, `score.py`
- Flood forecasts scored per event and lead, and false alarms (`events.csv`, `peaks.csv`, `false_alarms.csv`): `src/pegel/evaluation/flood_scores.py`
- Upstream model, model 4 of the ladder (`upstream`), fitted per lead on the change: `src/pegel/evaluation/models/simple.py`
- Curated change models v2 `rain_change:v2:split` and `ridge:change:v2` (named physical inputs per lead, inner-split candidate list): `src/pegel/evaluation/models/curated.py`, `analysis/model-evaluation/models-v2-candidates.csv`
- Learnings about models and evaluation, append-only: `analysis/model-evaluation/learnings.md`
- Preliminary data analysis (target, gauges, radar, ICON-D2), append-only: `analysis/preliminary-data-analysis.md`
- Run report and experiment log (`python -m pegel.evaluation.report <run dir>`, plots and one appended section per run): `src/pegel/evaluation/report.py`, `report_tables.py`, `report_plots.py`, `analysis/model-evaluation/`
- Forecast replay page per run, one self-contained HTML file (`python -m pegel.evaluation.replay <run dir> <eval.parquet>`, writes `replay.html`): `src/pegel/evaluation/replay.py`, `replay.html`
- Lead timeline page, 3 h vs 24 h ahead over the whole test period (`python -m pegel.evaluation.timeline <run dir> <eval.parquet>`, writes `timeline.html`): `src/pegel/evaluation/timeline.py`, `timeline.html`
- How the evaluation works (data, split, flood events, metrics) and every model on one page: `docs/evaluation.md`, `docs/models.md`, `analysis/model-evaluation/methodology_plots.py`

## Layout

```
pyproject.toml, uv.lock     Python project (uv)
Dockerfile                  two targets: jobs image and API image
mise.toml                   versions of node, pnpm, opentofu, dbmate, gitleaks
src/pegel/
  config.py                 loads config/pegel.json
  core/                     pure logic, no I/O: cleaning, features, model, categories
  adapters/                 talks to the outside: sources (influx, gauges, rain), storage, logging
  api/                      FastAPI app and response schemas
  jobs/                     entry points: run_hourly, run_training, run_backup
tests/
db/
  migrations/               numbered SQL files, run with dbmate
  schema.sql                generated by dbmate, never edit by hand
web/                        Astro + React + TypeScript site
infra/
  bootstrap/                state bucket and GitHub OIDC roles, applied by hand once
  prod/                     everything else
config/pegel.json           categories, horizons, stations, freshness thresholds
scripts/                    influx-query.sh, refresh-schema.sh, generate_records.py
docs/                       architecture, setup guides, decision records
```

`web/` and `infra/` will get their own `AGENTS.md` with the details for that folder.

Already there today:
- `.claude/rules/` — standards for code style, testing, git, pipelines, ML and operations
- `.claude/hooks/` — Claude Code hooks, registered in `.claude/settings.json`
- `.github/` — PR template and CI workflows (`secret-scan.yml`: gitleaks; `python.yml`: mypy, pytest, ruff)
- `.githooks/` — gitleaks pre-commit hook; enable with `git config core.hooksPath .githooks`
- `.env.example` — template for local config; real values go in the gitignored `.env` and `.env.local`
- `docs/setup-neon.md` — one-time manual Neon setup
- `docs/decisions/` — decision records, numbered `0001-…`

## Commands

### Setup

```
mise install                 # tools in the pinned versions
brew install libomp          # macOS only: lightgbm needs OpenMP
uv sync                      # Python and its dependencies
uv sync --group analysis     # plus pyarrow and matplotlib for model evaluation
cd web && pnpm install       # website dependencies
git config core.hooksPath .githooks
```

### Check

Always in this order: type check, then tests, then lint.

Python, from the repo root:
```
uv run mypy src tests
uv run pytest                # starts a throwaway Postgres container (needs Docker)
uv run ruff check . && uv run ruff format --check .
```

Website, in `web/`:
```
pnpm astro check
pnpm vitest run
pnpm biome check .
```

Infrastructure, in `infra/prod/`:
```
tofu fmt -check -recursive
tofu init -backend=false && tofu validate
tflint
```

### Database

After every new migration in `db/migrations/`:
```
scripts/refresh-schema.sh
```

It migrates a throwaway Postgres container with the pinned dbmate image, rewrites `db/schema.sql` and then `src/pegel/adapters/storage/records.py` (via `scripts/generate_records.py`). Needs Docker; never touches Neon. Commit both files. CI reruns it and fails if either is out of date.

To migrate the Neon `dev` branch (`DATABASE_URL` in `.env.local`, direct string):
```
mise exec -- dbmate --env-file .env.local --no-dump-schema migrate
```

`prod` is migrated by the deploy job (`.github/workflows/infra.yml`) on merge to `main`, after the image push and before the Lambda moves to the new image. Its connection string is in Secrets Manager (`deilbach-pegel/migrate-database-url`). Migrate `dev` first and check the code against it.

For the minute or two between migrate and the end of `tofu apply`, the old code runs on the new schema. Prefer migrations it survives: a new column nullable or with a default, `NOT NULL` in a later migration. If a migration does break the old code, watch the deploy so that stretch doesn't cross :30, or accept that one hourly run fails. For a migration that deletes or rewrites data, take a Neon snapshot of prod before merging, or rely on the 6-hour restore window.

Emergency only, if CI can't reach Neon: copy the direct `pegel_owner` string of `prod` from the Neon console and pass it from the clipboard, so it never lands in the shell history:
```
DATABASE_URL="$(pbpaste)" mise exec -- dbmate --no-dump-schema migrate
pbcopy </dev/null
```

### Run locally

Local runs use the Neon `dev` branch. Its connection strings go in `.env.local`; never put the `prod` ones there.

```
uv run uvicorn pegel.api.app:app --reload      # API on localhost:8000, docs at /api/docs
cd web && pnpm dev                             # website, talks to the local API
scripts/influx-query.sh                        # check access to the source database
docker build --platform linux/arm64 --target jobs .   # the Lambda jobs image
```

The CLI reads `.env` and `.env.local` from the main checkout (also from a worktree); variables already set in the shell win.

```
uv run pegel run-hourly                        # ingest and clean the last hours, save a persistence forecast
uv run pegel run-hourly --issued-at 2026-10-12T13:30Z   # rerun a past issue time
```

### Backfill

Loads history in monthly chunks with the same code the hourly job uses. It's the one case where a laptop writes to prod. Pass the prod jobs connection string from the clipboard for that run only (`JOBS_DATABASE_URL="$(pbpaste)" uv run pegel backfill …`, then `pbcopy </dev/null`), never in `.env.local`.

```
uv run pegel backfill --source influx --from 2023-03-01
```

Changing a station's `level_offset_cm` needs a data migration like `db/migrations/20261014120000_shift_kupferdreh_levels.sql`, not a re-ingest: the upsert would treat every shifted value as a revision.

After loading Kupferdreh history, or after changing the `cleaning` settings, rewrite its cleaned series. It needs only the database:
```
uv run pegel clean --from 2023-03-01 [--to 2026-01-01]
```

The upstream LANUV gauges load from the open data files instead: download `Ruhreinzugsgebiet-NRW-W_{decade}_EPSG25832_CSV.zip` from https://www.opengeodata.nrw.de/produkte/umwelt_klima/wasser/oberflaechengewaesser/hydro/w/, extract the `*_Wasserstand_cm.csv` files of our stations into a folder outside the repo, and pass it with `--path`. Without `--station` it loads all LANUV stations. From 2000 the data is regular (15 minutes or finer); before that Langenberg is sparse.

The ICON-D2 rain forecast archive comes from Open-Meteo. It needs only the jobs database, no Influx; details in `docs/catchment.md`:
```
uv run pegel backfill-forecast --from 2024-02-01
```
```
uv run pegel backfill --source lanuv-files --path <folder> --from 2000-01-01 [--station langenberg]
```

Radar rain loads from DWD's archives: monthly tars (about 180 MB each) before 2025, single hourly files from 2025 on. Downloads stay in the cache folder, so reruns are quick; delete it when done.
```
uv run pegel backfill-radar --from 2023-01-01 [--to 2026-10-01] [--cache-dir ~/.cache/deilbach-pegel/radolan]
```

### Evaluation dataset

The frozen dataset for model evaluation (docs/decisions/0008) is built by a person from prod. It only reads: every transaction is read-only. It needs the `analysis` group (`uv sync --group analysis`) and writes `eval.parquet` and `eval.manifest.json` to a folder outside the repo; it never overwrites them. `--to` is inclusive.
```
JOBS_DATABASE_URL="$(pbpaste)" uv run --group analysis pegel build-eval-set --from 2024-02-01 --to 2026-04-12 --out ~/data/deilbach-pegel/eval/2026-10-14/
pbcopy </dev/null
```

### Deploy

Only by merging to `main`. GitHub Actions builds the images, migrates the prod database, runs `tofu apply` and uploads the website. Never run `tofu apply` for `infra/prod/` from a laptop. The only exception is `infra/bootstrap/`, which is applied by hand once.
