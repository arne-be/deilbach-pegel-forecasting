# 0008 · Model evaluation and selection

- **Status:** accepted
- **Date:** 2026-10-14

## Goal

Find the best point forecast for Kupferdreh for leads 1 to 24 hours. Every model is scored on the same issue times, the same targets and the same folds. The result is a table and a graph of the error per lead time for every model.

## Decisions

### Scope

**Point forecasts only.** No quantiles, no CRPS. The uncertainty band comes later, from the errors per lead time of the chosen model.

**Leads 1 to 24 hours.** The archived ICON-D2 data can't support leads beyond 24 hours (see below). Leads 25 to 48 are not evaluated here.

**No automatic retraining.** A manual script trains, predicts and scores. We run it, read the results and decide by hand. This replaces weekly retraining in `.claude/rules/data-and-ml.md` for now.

### Data

**Window: 2024-02-01 to 2026-04-12.** It starts with the ICON-D2 archive and ends with the Langenberg open data. Every issue time in it has Kupferdreh, radar, Langenberg, Nierenhof and ICON-D2. That gives about 19,200 issue times.

**Inputs:** Kupferdreh (cleaned), Langenberg, Nierenhof, radar rain, ICON-D2 rain. Neviges is left out: it only has data from 2024-12 to 2025-06.

**Issue times are hh:30 UTC**, as live. The target for lead k is the cleaned Kupferdreh reading at hh+k:22.

**Only data available at the issue time.** Every input is read as of its `available_at`, not its `valid_at`. The existing reads (`fetch_values`, `newest_value`) filter on `valid_at`, so the evaluation gets its own as-of query.

**Gaps stay gaps.** A missing target is NaN and is left out of the scores. Missing inputs are filled only inside model training, never stored.

**One frozen dataset.** `pegel build-eval-set` writes one Parquet file, one row per issue time, with a manifest (window, config, code commit). All models read the same file.

### ICON-D2 input

**Every issue time gets the next 24 hours of rain forecast.** For each valid hour we take the value from the newest run that was available at the issue time. Features are the 24 hourly sums from hh:00 to hh+23:00, for the catchment mean and the ring p90, plus the forecast lead of each value.

**The archive forces a stitch.** ICON-D2 runs every 3 hours and forecasts 48 hours ahead. Live, the newest run is 2.5 to 5.5 hours old, so it always covers 24 hours and more. But the Open-Meteo archive does not keep whole runs before 2026-04. For each valid hour it keeps only two values: one from a run 1 to 3 hours earlier, one from a run 25 to 27 hours earlier. At an issue time the fresh one is never known yet, so only the day-old one is used. So in the archive every hour ahead gets a forecast with a lead of 25 to 27 hours. Live, the lead grows with the hour ahead, from about 4 hours at +1 to about 27 hours at +24. Coverage is fine: the archive always has a known value up to 22.5 to 24.5 hours ahead, so the 24 sums are always complete. Starting in 2024 does not avoid this; it is how the archive is stored.

**We accept the stitch and measure its effect.** A model trained on old forecasts will trust short-lead rain less than it could. We check the size of this with the full runs from Open-Meteo Single Runs (2026-04 to 2026-10) and with a live shadow run from 2026-10-12.

### Folds

**Four expanding-window folds.** Training always starts on 2024-02-01 and ends where the test starts. A 24-hour embargo drops the last training issue times, whose targets reach into the test.

| Fold | Test period | Floods above 95 cm |
|---|---|---|
| F1 | 2024-10-01 to 2024-12-31 | 4 |
| F2 | 2025-01-01 to 2025-03-31 | 2 |
| F3 | 2025-04-01 to 2025-09-30 | 0 |
| F4 | 2025-10-01 to 2026-04-12 | 0 |

**No random splits, no `TimeSeriesSplit`.** The fold dates are fixed in code.

**No separate hold-out period.** There are too few floods to spare. To limit overfitting by selection, the dataset, folds and metrics are frozen before the first model is scored.

### Metrics

**The main metric is MAE per lead time**, for each lead 1 to 24, for each model and fold. From it we draw one line per model: error over lead time.

**Also per lead:** RMSE, bias, and skill against persistence (1 − MAE_model / MAE_persistence).

**Two subsets.** All issue times is the headline. High water (level above 75 cm at the issue time or at the target) is shown next to it, because calm days dominate the average.

**Events.** For each flood above 95 cm: error in peak height and peak timing. Hits, misses and false alarms at 95 cm and at 145 cm (category 2).

**Confidence.** Bootstrap over whole days for the mean MAE per lead.

**Output.** `predictions.parquet` (issue time, lead, model, fold, prediction, target) and `scores.csv` (model, fold, subset, lead, n, MAE, RMSE, bias, skill). Plots are made from these files.

**Thresholds live in config.** 75 and 95 cm go into `config/pegel.json`; 145 cm is already category 2 there.

### Model ladder

**Simple first.** We start with five simple models. A more complex model is only tried when the simple ones are scored and understood.

1. **Persistence.** The last cleaned level, for every lead.
2. **Recession to base.** The level moves back towards a base level (median of the last 30 days) with one fitted factor per lead.
3. **Damped trend.** The last level plus the change over the last hour, with one fitted factor per lead.
4. **Upstream change.** The last level plus the recent change at Langenberg and Nierenhof, fitted per lead. The upstream wave reaches Kupferdreh later.
5. **Linear model per lead (ridge).** Recent levels, upstream levels, radar sums and ICON-D2 sums.

Then:

6. **LightGBM, one model per lead**, with the same features as the linear model.

**Each learned model is tried with three targets**, as separate entries in the scores:

- **Level:** the level at hh+k:22.
- **Change:** the level at hh+k:22 minus the last level at the issue time. The model's prediction is added to the last level.
- **Hourly step:** the level at hh+k:22 minus the level one hour earlier. Each lead gets its own model. The steps are summed onto the last level. A training row needs both readings of its step.

Models 2 to 4 already predict a change from the last level, so they get no variants. For the ridge model, the hourly step gives the same forecast as the change, because the sum of linear models is a linear model. So ridge is tried with level and change, and LightGBM with all three.

Anything beyond that (other boosting setups, neural networks) only if LightGBM leaves a clear gap, for example on rising limbs.

**Every model has the same interface:** `fit(train rows)` and `predict(rows) → 24 values per issue time`. Feature code lives in `src/pegel/core/features.py` and is shared with the live job.

**Seeded.** Every model with randomness gets a fixed seed.

### Selection rule

**A model wins over a simpler one** when its mean MAE over leads 1 to 24 is lower in at least 3 of 4 folds, and its high-water MAE is not worse. Otherwise the simpler model stays.

**Ties go to the simpler model.**

**The chosen model goes live by hand**, trained on the whole window by the manual script and saved with its data window, config, code commit and scores.

### Dependencies

A uv dependency group `analysis` with pandas, pyarrow, scikit-learn and lightgbm, pinned. Not in the Lambda image until a model needs it live.

### Order of work

1. As-of query on `available_at`.
2. Feature code.
3. `pegel build-eval-set`.
4. Metrics.
5. Folds, harness and persistence.
6. The other simple models and the first report.
7. LightGBM.

## Accepted

- Training sees only rain forecasts with a 25 to 27 hour lead; live, short hours get much shorter leads. The archive scores are likely a bit pessimistic for rain-driven leads.
- Only 6 floods fall in the test folds, all in winter. There is no summer thunderstorm event to test on.
- LANUV is sometimes later than the 25 minutes we assume (for example 2026-10-14 12:30). The backtest assumes 25 minutes; live may have one hour less upstream data now and then.
- Picking the best of six models on the same folds is mild overfitting to those folds.

## Rejected

- **Training from 2023-03 with ICON-D2 left empty.** More calm data, but two input regimes in one model.
- **Probabilistic forecasts and CRPS now.** First get the point forecast right.
- **Forecasting libraries** (skforecast, sktime, darts, Nixtla). The models are simple enough without them, and the harness is a few functions.
- **Random or shuffled splits.** They leak the future.
- **Automatic retraining.** No point until we know which model to retrain.

## Open

- What the live forecast shows for leads 25 to 48 hours.
- How large the stitch effect is, once measured on the Single Runs data.
