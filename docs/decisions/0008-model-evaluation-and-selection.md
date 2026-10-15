# 0008 · Model evaluation and selection

- **Status:** accepted
- **Date:** 2026-10-14, flood events and flood forecasts revised 2026-10-15

## Goal

Find the best point forecast for Kupferdreh for leads 1 to 24 hours. Every model is scored on the same issue times, the same targets and the same folds. The result is a table and a graph of the error per lead time for every model.

How it works, with figures: [evaluation.md](../evaluation.md). The models: [models.md](../models.md).

## Decisions

### Scope

**Point forecasts only.** No quantiles, no CRPS. The uncertainty band comes later, from the errors per lead time of the chosen model.

**Leads 1 to 24 hours.** The archived ICON-D2 data can't support leads beyond 24 hours (see below). Leads 25 to 48 are not evaluated here.

**No automatic retraining.** A manual script trains, predicts and scores. We run it, read the results and decide by hand. This replaces weekly retraining in `.claude/rules/data-and-ml.md` for now.

### Data

**Window: 2024-02-01 to 2026-04-12.** It starts with the ICON-D2 archive and ends with the Langenberg open data. Every issue time in it has all inputs below. That gives about 19,200 issue times.

**Inputs:**

- **Kupferdreh level**, cleaned (`kupferdreh:cleaned_kalman`).
- **Upstream levels:** Langenberg and Nierenhof. Neviges is left out: it only has data from 2024-12 to 2025-06.
- **Observed rain:** DWD RADOLAN RW radar, hourly and adjusted to rain gauges. The zone means and the catchment maximum.
- **Forecast rain:** ICON-D2, catchment mean and ring p90 (see below).

**Issue times are hh:30 UTC**, as live. The target for lead k is the cleaned Kupferdreh reading closest to hh+k:22, at most 10 minutes off; otherwise the target is missing.

**Only data available at the issue time.** Every input is read as of its `available_at`, not its `valid_at`. `fetch_values` already returns `available_at`, so the build fetches each series once for the whole window and filters per issue time in pure code. Input forecasts get a range fetch of their own.

**Revisions are not a problem today.** On 2026-10-14, no value of `kupferdreh:cleaned_kalman` on prod had an `available_at` more than 2 hours after its `valid_at`. So a strict as-of filter loses no data.

**Gaps stay gaps.** A missing target is NaN and is left out of the scores. Missing inputs are never filled in the dataset. LightGBM handles them itself. Ridge fills them with the last known value and gets a flag that the value was missing.

**One frozen dataset.** `pegel build-eval-set` writes one Parquet file, one row per issue time, with a manifest: window, config, code commit, row count and checksum. It holds history windows, not features: 24 hours of hourly levels per gauge, 7 days of radar, and all 24 ICON-D2 hours. Features are computed from these when a model is fitted.

**The dataset lives outside the repo**, for example in `~/data/deilbach-pegel/eval/<date>/`, and may be copied to S3 by hand. It is never committed. The checksum in the manifest ties every result to the file.

**The dataset is built by a person, read-only, from prod.** Dev only has a few days of history.

### ICON-D2 input

**Every issue time gets the next 24 hours of rain forecast.** For each valid hour we take the value from the newest run that was available at the issue time. Features are the 24 hourly sums from hh:00 to hh+23:00, for the catchment mean and the ring p90, plus the forecast lead of each value.

**The archive forces a stitch.** ICON-D2 runs every 3 hours and forecasts 48 hours ahead. Live, the newest run is 2.5 to 5.5 hours old, so it always covers 24 hours and more. But the Open-Meteo archive does not keep whole runs before 2026-04. For each valid hour it keeps only two values: one from a run 1 to 3 hours earlier, one from a run 25 to 27 hours earlier. For the first two columns, the current and the next hour, the fresh value from a run 2 to 3 hours earlier is sometimes already available at the issue time, and then it is used. Every later hour gets the day-old value, with a lead of 25 to 27 hours. Live, the lead grows with the hour ahead, from about 4 hours at +1 to about 27 hours at +24. Coverage is fine: the archive always has a known value up to 22.5 to 24.5 hours ahead, so the 24 sums are always complete. Starting in 2024 does not avoid this; it is how the archive is stored.

**We accept the stitch and measure its effect.** A model trained on old forecasts will trust short-lead rain less than it could. We check the size of this with the full runs from Open-Meteo Single Runs (2026-04 to 2026-10) and with a live shadow run from 2026-10-12.

### Folds

**Four expanding-window folds.** Training always starts on 2024-02-01 and ends where the test starts. A 24-hour embargo drops the last training issue times, whose targets reach into the test.

| Fold | Test period | Flood events (peak above 75 cm) | of them above 95 cm |
|---|---|---|---|
| F1 | 2024-10-01 to 2024-12-31 | 4 | 4 |
| F2 | 2025-01-01 to 2025-03-31 | 3 | 2 |
| F3 | 2025-04-01 to 2025-09-30 | 1 | 0 |
| F4 | 2025-10-01 to 2026-04-12 | 5 | 0 |

**No random splits, no `TimeSeriesSplit`.** The fold dates are fixed in code.

**No separate hold-out period.** There are too few floods to spare. To limit overfitting by selection, the dataset, folds and metrics are frozen before the first model is scored.

**The live shadow run is the real hold-out.** The final choice is confirmed on live forecasts from 2026-10-12 on before it replaces persistence on the website.

### Metrics

**The main metric is MAE per lead time**, for each lead 1 to 24, for each model and fold. From it we draw one line per model: error over lead time.

**Also per lead:** RMSE, bias, and skill against persistence (1 − MAE_model / MAE_persistence). No NSE or KGE.

**Two subsets.** All issue times is the headline. High water (level above 75 cm at the issue time or at the target) is shown next to it, because calm days dominate the average.

**Only the cleaned series.** Targets, the high water subset, events and flood forecasts all use the cleaned Kupferdreh level (`kupferdreh:cleaned_kalman`). The raw series is only the input that cleaning is derived from.

**Events.** A flood event is one rise of the river and its fall back, with a peak above 75 cm. It starts at the foot of a fast rise and lasts until the level is back near where it started, or has stopped falling below 75 cm; a new rise before then belongs to the same event. The exact rule is in [evaluation.md](../evaluation.md#flood-events).

**Flood forecasts are scored per event, at the peak.** For each event, model and lead of 24, 12, 6, 3 and 1 hour, we take the forecast issued that many hours before the peak and ask three things: did it see more than half the rise (predicted, yes or no), what share of the rise did it see (size, from the pre-event level), and how many hours off was its peak (timing). An event with two peaks is scored on the higher one. The exact rules are in [evaluation.md](../evaluation.md#flood-forecasts).

Why: a model should be judged on what matters on a flood day, whether and how early it sees the peak coming, and the scores should be readable at a glance. The earlier rules, warnings per threshold crossing with a ±6 hour match and per-lead hits, were hard to follow and left out every flood that stays below 95 cm.

**False alarms are the counterweight.** A forecast that shows a new event while none is running or starting within 24 hours is a false alarm; a run of such forecasts counts once. Reported as the count divided by the number of test months.

**A forecast replay per run.** An interactive page steps through the forecasts of each event, from 24 hours before the peak to its end, so models can be compared by eye. A static peak track per event goes into the experiment log.

**Few events.** With 13 events in the test folds, differences of one or two predicted events can't rank models.

**Lag check.** On high water, the time shift that best fits the forecast to the observed level. If that shift equals the lead, the model is only a delayed persistence.

**Confidence.** A bootstrap over whole days, 1000 resamples, 90 % intervals, fixed seed. It is computed on the difference in MAE to persistence, per lead.

**Output.** `predictions.parquet` (issue time, lead, model, fold, prediction, target) and `scores.csv` (model, fold, subset, lead, n, MAE, RMSE, bias, skill). Plots are made from these files.

**Thresholds live in config.** 75 and 95 cm go into `config/pegel.json`; the category bounds are already there.

### Experiment log

**Every scored run is appended to `analysis/model-evaluation/experiments.md`.** One section per run: date, code commit, dataset checksum, the models with their targets and feature sets, the mean MAE and skill per subset, the plots (MAE per lead for both subsets, skill per lead, and the event plots), and a short note on what was tried and what we learned. The plots are PNG files in `analysis/model-evaluation/plots/<run>/`, committed and embedded in the section. Nothing in it is edited afterwards; a later run that changes a conclusion says so in its own section. This keeps every comparison of models, features and approaches in one place.

### Model ladder

**Simple first.** We start with five simple models. A more complex model is only tried when the simple ones are scored and understood.

1. **Persistence.** The last cleaned level, for every lead.
2. **Recession to base.** The level moves back towards a base level with one fitted factor per lead. The base level is the median of the cleaned hourly levels of the last 30 days, as of the issue time.
3. **Damped trend.** The last level plus the change over the last 3 hours, with one fitted factor per lead. A 1-hour change is too noisy.
4. **Upstream change.** The last level plus the recent change at Langenberg and Nierenhof, fitted per lead. The upstream wave reaches Kupferdreh later.
5. **Linear model per lead (ridge).** The features below.

Then:

6. **LightGBM, one model per lead**, with the same features as the linear model. Also tried with `linear_tree`, because plain trees can't forecast above the highest level they trained on.

**Features**, shared by ridge and LightGBM:

- Kupferdreh: the last level, the levels of the last 24 hours, and the 30-day base level.
- Upstream: Langenberg and Nierenhof levels at lags 0 to 6 hours, and their 1-hour and 3-hour changes. The travel time to Kupferdreh is measured by cross-correlation on high water, not assumed.
- Observed rain: radar sums over the last 1, 3, 6, 12, 24 and 72 hours and 7 days.
- Forecast rain: the 24 ICON-D2 hours.
- Time of year as sine and cosine.
- The error of the lead-1 forecast issued one hour earlier, which can be checked at the issue time.

**Each learned model is tried with three targets**, as separate entries in the scores:

- **Level:** the level at hh+k:22.
- **Change:** the level at hh+k:22 minus the last level at the issue time. The model's prediction is added to the last level.
- **Hourly step:** the level at hh+k:22 minus the level one hour earlier. One model for all 24 steps, with the lead as a feature and the ICON-D2 rain of the 6 hours before that step. Each issue time gives 24 training rows. The steps are summed onto the last level. A row with a missing step is dropped from training.

Models 2 to 4 already predict a change from the last level, so they get no variants. Ridge is tried with level and change only: a linear model can't use the lead feature the way the step model needs. LightGBM is tried with all three.

**Not recursive.** A one-hour model fed its own output would need future upstream levels and radar, which aren't known at the issue time, and its errors would add up.

**Extrapolation test.** LightGBM is also trained once without the largest flood and scored on it.

Anything beyond that (other boosting setups, neural networks) only if LightGBM leaves a clear gap, for example on rising limbs.

**Every model has the same interface:** `fit(train rows)` and `predict(rows) → 24 values per issue time`. Feature code lives in `src/pegel/core/features.py` and is shared with the live job.

**Seeded.** Every model with randomness gets a fixed seed.

### Selection rule

**A model wins over a simpler one** when its mean MAE over leads 1 to 24 is lower in at least 3 of 4 folds, and its high-water MAE, pooled over all folds, is not worse. Otherwise the simpler model stays.

**Flood forecasts are reported, not used to select yet.** They don't decide between models until we have analysed them and agreed on how many false alarms are acceptable.

**Ties go to the simpler model.**

**The chosen model goes live by hand**, trained on the whole window by the manual script and saved with its data window, config, code commit and scores.

### Dependencies

**Everything the live forecast needs goes into the main dependencies and the Lambda image:** pandas for the features, scikit-learn and lightgbm for the models. The live job computes features with the same code as training, and any model from the ladder can go live without a dependency change.

**A uv dependency group `analysis`** with what only the evaluation needs: pyarrow for the Parquet files and matplotlib for the plots. Pinned, not in the Lambda image.

## Accepted

- Training sees only rain forecasts with a 25 to 27 hour lead; live, short hours get much shorter leads. The archive scores are likely a bit pessimistic for rain-driven leads.
- Only 13 flood events fall in the test folds, and only 6 of them pass 95 cm. All but one are in winter. One event is in April; there is no summer thunderstorm event to test on.
- LANUV is sometimes later than the 25 minutes we assume (for example 2026-10-14 12:30). The backtest assumes 25 minutes; live may have one hour less upstream data now and then.
- Picking the best of many models on the same folds is mild overfitting to those folds. The live shadow run checks it.
- The Lambda image gets bigger with pandas, scikit-learn and lightgbm (and their numpy and scipy).

## Rejected

- **Training from 2023-03 with ICON-D2 left empty.** More calm data, but two input regimes in one model.
- **Warnings per threshold crossing** (95 cm and each category bound, matched within ±6 hours) and **per-lead hits.** Used in the first runs, replaced on 2026-10-15 by flood forecasts per event: hard to read, and blind to floods below 95 cm.
- **Probabilistic forecasts and CRPS now.** First get the point forecast right.
- **Forecasting libraries** (skforecast, sktime, darts, Nixtla). The models are simple enough without them, and the harness is a few functions.
- **Random or shuffled splits.** They leak the future.
- **Automatic retraining.** No point until we know which model to retrain.
- **A run without ICON-D2 for every learned model.** It doubles the runs for little: the learnings already show ICON-D2 is the strongest input, and the live shadow run shows what fresh runs add.
- **LSTM.** One gauge and two years of data is the case where it does badly ([Kratzert et al.](https://research.google/pubs/hess-opinions-never-train-a-long-short-term-memory-lstm-network-on-a-single-basin/)). Only reconsider by fine-tuning a model pretrained on many basins.
- **NSE and KGE.** Skill against persistence says more for short leads ([Knoben et al. 2019](https://hess.copernicus.org/articles/23/4323/2019/)).

## Later, outside this plan

- Weighting high water in training, an event table instead of event averages, and longer bootstrap blocks.
- Measuring the stitch effect on the Single Runs data, the live shadow run, and where the chosen model is stored.
- What the live forecast shows for leads 25 to 48 hours.
