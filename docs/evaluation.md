# Model evaluation

How we score forecast models for Kupferdreh: the data, the split into training and test periods, the flood events, the metrics and how to run it. The reasons behind each choice are in [decision 0008](decisions/0008-model-evaluation-and-selection.md). The models themselves are in [models.md](models.md). Results go in the [experiment log](../analysis/model-evaluation/experiments.md), insights in the [learnings](../analysis/model-evaluation/learnings.md), what we know about the data in the [preliminary data analysis](../analysis/preliminary-data-analysis.md).

## Running it

1. **Build the dataset once.** `pegel build-eval-set`, read-only from prod (command in `AGENTS.md`). Every input as of its issue time. Frozen as `eval.parquet` with a checksum in `eval.manifest.json`, outside the repo.
2. **Fit and predict.** `python -m pegel.evaluation.predict <dataset> --out <dir>` trains every registered model on each fold's training rows and predicts its test rows. Writes `predictions.parquet`.
3. **Score.** `python -m pegel.evaluation.score <predictions> <dataset> --out <dir>` writes `scores.csv`, `bootstrap.csv`, `events.csv`, `peaks.csv`, `crossings.csv`, `false_alarms.csv`, `lag.csv` and `alarms.csv` (per-lead hits, a diagnostic only).
4. **Log it.** `python -m pegel.evaluation.report <run dir>` appends a section with tables and plots to `analysis/model-evaluation/experiments.md`. Add what we learned to `learnings.md`.

## Data

- **Window:** issue times from 2024-02-01 to 2026-04-12, hourly at hh:30 UTC, 19,248 rows. It starts with the ICON-D2 archive and ends where the LANUV open data for Langenberg ends.
- **One row per issue time**, holding only what was known then: Kupferdreh, Langenberg and Nierenhof levels for the last 24 hours, radar rain for the last 7 days, and the ICON-D2 rain forecast for the next 24 hours.
- **Targets:** the Kupferdreh level 1 to 24 hours after the issue time. Training sees them; prediction never does.
- **Only the cleaned Kupferdreh series** (`kupferdreh:cleaned_kalman`), for inputs, targets, high water, events and warnings.

![One dataset row: 24 hourly lags of levels and radar before the issue time, 24 ICON-D2 hours after it, and 24 targets](images/evaluation-dataset-row.svg)

Left of the red line is what was known at 12:30 on 19 Nov 2024, a flood day. Blue: observed, or a fresh ICON value. Orange: a day-old ICON value. Red circles: the targets.

## The ICON-D2 archive

Before April 2026 the archive only has day-old ICON-D2 forecasts for most hours, so every model trains and tests on 25–27 hour old rain forecasts. Live, the short hours get much fresher ones. The backtest is fair between models, but it likely undervalues rain-driven leads; the live shadow run from 12 Oct 2026 has the final say. Details and figures: [catchment.md](catchment.md#what-a-model-sees-at-an-issue-time).

## Data split

Four expanding-window folds, fixed in code (`src/pegel/evaluation/contract.py`). Each model is trained fresh on everything from 2024-02-01 up to its test period. The last 24 hours before each test period are dropped from training, because their targets reach into it.

![The cleaned Kupferdreh level from February 2024 to April 2026 with the test periods shaded, and the four folds below it](images/evaluation-methodology/split.png)

| fold | test period | training issue times | test issue times | test issue times above 75 cm | flood events |
|---|---|---|---|---|---|
| F1 | 2024-10-01 – 2024-12-31 | 5,808 | 2,208 | 377 | 4 |
| F2 | 2025-01-01 – 2025-03-31 | 8,016 | 2,160 | 276 | 4 |
| F3 | 2025-04-01 – 2025-09-30 | 10,176 | 4,392 | 15 | 0 |
| F4 | 2025-10-01 – 2026-04-12 | 14,568 | 4,656 | 297 | 0 |

- **All eight flood events are in F1 and F2**, winter 2024/25. F3 is summer, with almost no high water. F4 has high water, but its peaks stop just below 95 cm.
- **Training before F1 has only two floods**, both in February 2024 (104 cm and 122 cm).
- **There is no hold-out period.** Every flood is needed in a test fold. The live shadow run is the check on overfitting.

## Flood events

A flood event is a time above 95 cm. Spells whose peaks are less than 24 hours apart are merged into one event (`src/pegel/evaluation/events.py`).

| event | fold | above 95 cm from (UTC) | to (UTC) | peak (cm) | peak at (UTC) | radar, wettest cell, 48 h to peak (mm) |
|---|---|---|---|---|---|---|
| 1 | F1 | 2024-10-10 00:30 | 2024-10-10 08:30 | 120.7 | 2024-10-10 02:30 | 62.2 |
| 2 | F1 | 2024-11-19 10:30 | 2024-11-20 20:30 | 165.0 | 2024-11-19 17:30 | 118.4 |
| 3 | F1 | 2024-12-06 04:30 | 2024-12-06 05:30 | 97.3 | 2024-12-06 05:30 | 36.4 |
| 4 | F1 | 2024-12-22 01:30 | 2024-12-22 15:30 | 97.8 | 2024-12-22 13:30 | 46.2 |
| 5 | F2 | 2025-01-05 17:30 | 2025-01-08 01:30 | 125.4 | 2025-01-05 23:30 | 44.6 |
| 6 | F2 | 2025-01-08 07:30 | 2025-01-08 07:30 | 95.4 | 2025-01-08 07:30 | 46.3 |
| 7 | F2 | 2025-01-25 06:30 | 2025-01-26 22:30 | 105.0 | 2025-01-26 04:30 | 46.5 |
| 8 | F2 | 2025-01-27 04:30 | 2025-01-27 06:30 | 96.2 | 2025-01-27 06:30 | 33.9 |

**8 events, 6 first crossings.** Events 6 and 8 follow another event within hours. They count for peak errors, but not as first crossings for warnings (there was an hour above 95 cm in the 24 hours before). So the warning tables have 6 crossings at 95 cm. Only event 2 crosses the first category bound, 145 cm.

Each plot shows the event from 36 hours before it starts to 48 hours after it ends. Top: the cleaned Kupferdreh level and the two upstream gauges, with the time above 95 cm shaded. Bottom: hourly radar rain in the wettest radar cell of the catchment (the dataset's `catchment` series is the cell maximum, not a mean). The figures are redrawn with:

```
uv run --group analysis python analysis/model-evaluation/methodology_plots.py \
    ~/data/deilbach-pegel/eval/2026-10-14/eval.parquet docs/images/evaluation-methodology
```

### Event 1 · 10 Oct 2024, 120.7 cm

![Event 1](images/evaluation-methodology/event-1-2024-10-10.png)

### Event 2 · 19 Nov 2024, 165.0 cm

The largest flood in the window and the only one above 145 cm. ICON-D2 badly underforecast its rain. In the 48 hours before it the zone means got 47 to 70 mm, the wettest cell 118 mm.

![Event 2](images/evaluation-methodology/event-2-2024-11-19.png)

### Event 3 · 6 Dec 2024, 97.3 cm

![Event 3](images/evaluation-methodology/event-3-2024-12-06.png)

### Event 4 · 22 Dec 2024, 97.8 cm

![Event 4](images/evaluation-methodology/event-4-2024-12-22.png)

### Event 5 · 5 Jan 2025, 125.4 cm

Above 95 cm for more than two days.

![Event 5](images/evaluation-methodology/event-5-2025-01-05.png)

### Event 6 · 8 Jan 2025, 95.4 cm

A one-hour return above 95 cm, six hours after the last hour above 95 cm in event 5.

![Event 6](images/evaluation-methodology/event-6-2025-01-08.png)

### Event 7 · 26 Jan 2025, 105.0 cm

![Event 7](images/evaluation-methodology/event-7-2025-01-26.png)

### Event 8 · 27 Jan 2025, 96.2 cm

A second peak, six hours after the last hour above 95 cm in event 7.

![Event 8](images/evaluation-methodology/event-8-2025-01-27.png)

## Metrics

Every score is computed for **all issue times** (mostly low, slowly falling water) and for **high water**: the level is above 75 cm at the issue time or at the target time.

- **MAE per lead time**, 1 to 24 hours, per model and fold. The main metric.
- **Skill against persistence:** 1 − MAE / MAE of persistence (the last level held flat). Above 0 is better than doing nothing. A bootstrap over whole days gives a 90 % range for the difference to persistence.
- **Peaks:** for each event and lead k, the forecast issued k hours before the peak: its highest value minus the observed peak (height), and the time of its highest value minus the peak time (timing).
- **Warnings** at 95 cm and each category bound (145, 165, 185, 225 cm):
  - A first crossing is an hour above the threshold with no hour above it in the 24 hours before.
  - A forecast crosses when the last known level (at most 3 hours old) is not above the threshold and one of its 24 values is.
  - A first crossing is warned by every forecast issued before it whose crossing time is at most 6 hours off. It counts as a hit at 3 or 6 hours if the first such forecast came that early.
  - A forecast crossing with no observed crossing within 6 hours is a false alarm. A warning that stays up over several issue times counts once.
  - Warnings are reported, not used to select models yet.
- **Lag check:** on high water, the time shift that best fits the forecast to the observed level. If it equals the lead, the model is only a delayed persistence.

## Selection

A model wins over a simpler one when its mean MAE over leads 1 to 24 is lower in at least 3 of 4 folds, and its pooled high-water MAE is not worse. Ties go to the simpler model.

## Limits

- 8 flood events and 6 first crossings of 95 cm, all in winter, no summer thunderstorm. Differences of one or two warnings mean nothing.
- Training and test both use the day-old ICON-D2 archive. Live gets fresher rain forecasts.
- Picking the best of many models on the same folds overfits them a little. The live shadow run checks both.
