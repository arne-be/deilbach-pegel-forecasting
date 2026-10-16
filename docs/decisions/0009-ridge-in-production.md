# 0009 · ridge:change:v2 in production

- **Status:** accepted
- **Date:** 2026-10-15

## Decisions

**`ridge:change:v2` replaces persistence on the website.** It is the best model of the evaluation in [0008](0008-model-evaluation-and-selection.md): level with `rain_change:v2:split` over all issue times, better at high water, one flood more seen a day ahead. How it runs: [models.md](../models.md#in-production-ridgechangev2).

**Straight live, no shadow run first.** 0008 planned to confirm the model on live forecasts before it replaces persistence. We skip that: persistence never sees a flood coming, so even an unconfirmed model shows more. Live forecasts are now the hold-out.

**Trained by a script a person runs.** `pegel train-model` builds the rows from prod read-only with the evaluation's code, fits on all of them and writes one JSON file. No automatic retraining, as in 0008.

**Training window 2024-02-01 to 2026-04-12 for now.** Langenberg's open data ends on 2026-04-12, and the model counts a missing upstream change as 0. The window grows once the live upstream data covers the months after.

**The model file is JSON in the data bucket**, under `models/`, never overwritten. It holds the coefficients and what they were trained on: window, rows, code commit, config. No pickle, so loading a file can't run code.

**`forecast.model_file` in `config/pegel.json` picks the file.** A new model or a rollback is a reviewed config change. The Lambda already may read the bucket.

**The forecast covers 24 hours, not 48, for now.** The model has leads 1 to 24 only. A 48-hour model needs a rain forecast known 25 to 48 hours ahead at each issue time, and the ICON-D2 archive before 2026-04 doesn't keep one. Full runs exist from 2026-04, live upstream data from 2026-10. Once these cover enough months with floods, a 48-hour model is trained and evaluated like this one. Until then the forecast, its summaries and persistence stop at 24 hours. The rain forecast still fetches 48 hours, so the data builds up.

**Persistence stays the fallback.** The hourly job saves persistence first, then the ridge forecast. If the ridge step fails, the run goes on, and the API serves persistence while the ridge forecast is older than the newest persistence one. The page is never left on a stale forecast.

## Accepted

- No live check before going public. A bad live behaviour shows on the website first.
- The model was trained on day-old ICON-D2 rain; live runs are fresher, and a model that learned to trust day-old rain little may underuse them.
- The website shows 24 hours instead of the planned 48 until the data supports more.
- Each hourly run reads about 30 days of history to build its row.

## Rejected

- **Shadow run first** (0008). Safer, but delays a better forecast by weeks for a model that already beats persistence on every fold.
- **Holding the +24 h value flat for 25 to 48 hours.** Looks like a forecast but isn't one.
- **Fitting leads 25 to 48 without rain beyond 24 hours.** Would show the fall after a peak, but miss any rain still to come; better to wait for real data.
- **Pickle or joblib.** Ties the file to library versions and runs code on load.
- **A `current` pointer file on S3.** Rollback without a deploy, but the live model would no longer be visible in the repo.
