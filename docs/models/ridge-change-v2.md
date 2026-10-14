# Ridge change model, version 2

`ridge:change:v2` forecasts the Kupferdreh level 1 to 24 hours ahead as the last cleaned level plus a change, like [`rain_change:v2:split`](rain-change-v2.md), but from 20 curated inputs instead of 14, with ridge shrinkage. It replaces the about 200 columns of `ridge:change` (PR #70) with inputs that each have a physical reason. Code: `src/pegel/evaluation/models/curated.py` (`RIDGE_V2`).

It is a backtest model for now.

## Inputs, and why

All inputs of `rain_change:v2:split` (constant, distance to the 30-day base, Langenberg and Nierenhof 3-hour changes, radar 0–2 and 3–11 hours back, ICON-D2 sum over hours 1..k and its part above 5 mm, the recent rise faded over 24 h, Kupferdreh's 3-hour change from the newest reading, four summer hour terms), plus:

- **Kupferdreh's 1-hour change** from the newest reading, for the shortest leads.
- **The recent rise faded over 6 hours**, the fast part of the two-speed recession, next to the 24-hour one.
- **Radar 12 to 23 hours back**, for the longer falling limb.
- **ICON-D2 sums over hours 1 to 6 and 1 to 24**, the same for every lead: how much rain is coming soon and in the next day.
- **ICON-D2 sum 1..k times the last level / 10.** The data showed the same rain gives fewer cm from a high start. Its fitted coefficient is close to 0, so it adds little.

Not used, after the inner splits: Kupferdreh level lags, upstream levels, ICON p90, the radar zones (one catchment mean is enough), the catchment radar maximum, radar beyond 24 hours, the seasonal sine/cosine of `ridge:change` (the summer hour terms are used instead), and upstream changes cut off after 6 hours.

The rising split of `rain_change:split` is used here too: one coefficient set for rising rows, one for the rest.

## Fitting

Per lead and group, least squares with a ridge penalty of 100 on the inputs scaled to unit standard deviation; the constant is not penalised. The strength is fixed, not chosen per fold: `ridge:change` picked between 1 and 10,000 on different folds. 100 was chosen on the inner splits from 10, 100, 300, 1000 and a per-fold grid. 1000 had a slightly lower mean MAE there (2.36 against 2.41 cm), 100 the lower high-water MAE (4.91 against 5.11 cm); we took 100 because high water is where the model matters.

## Missing inputs

As in `rain_change:v2:split`: a missing upstream change, Kupferdreh change or recent rise counts as 0; anything else missing gives persistence.

## Results

From one run on the frozen dataset of 2026-10-14, the four folds of [decision 0008](../decisions/0008-model-evaluation-and-selection.md). MAE in cm, pooled over the folds. High water: above 75 cm at the issue time or at the target.

| Model | All +1 | All +6 | All +12 | All +24 | All, mean | High water +6 | High water +24 | High water, mean |
|---|---|---|---|---|---|---|---|---|
| persistence | 0.66 | 2.05 | 3.03 | 4.01 | 2.84 | 5.39 | 12.99 | 8.25 |
| ridge:change | 0.70 | 1.88 | 2.70 | 3.18 | 2.46 | 3.94 | 8.36 | 5.60 |
| rain_change:split | 0.66 | 1.80 | 2.53 | 2.98 | 2.31 | 3.76 | 7.60 | 5.22 |
| **ridge:change:v2** | 0.67 | 1.56 | 2.19 | 2.87 | 2.07 | 3.57 | 7.07 | 4.83 |

Per fold, mean MAE over leads 1 to 24, all issue times:

| Fold | ridge:change | rain_change:split | ridge:change:v2 |
|---|---|---|---|
| F1 | 3.730 | 2.506 | 2.283 |
| F2 | 1.716 | 1.799 | 1.682 |
| F3 | 2.727 | 2.730 | 2.467 |
| F4 | 1.932 | 2.034 | 1.770 |

It beats both `ridge:change` and `rain_change:split` in all four folds and has the lowest pooled high-water MAE of all models so far. At +24 h it is 1.15 cm better than persistence (90 % bootstrap interval −1.43 to −0.87 cm). Against `rain_change:v2:split` it is level over all issue times (2.07 both) and better at high water (4.83 against 5.10).

**Warnings at 95 cm** (crossing metric, 6 first crossings): 2 warned at least 3 and at least 6 hours ahead. 0.60 false alarms a month, more than any other model (`rain_change:split` 0.54, `ridge:change` 0.38). The 145 cm crossing is not warned 3 hours ahead; `ridge:change` did warn it.

## Known weaknesses

- **No gain at +1 h.** 0.67 cm, persistence 0.66, upstream 0.60.
- **Too low at high water.** Bias −1.73 cm at +6 h and −3.82 cm at +24 h.
- **More false alarms** than version 1, and one warning fewer than `ridge:change` at 3 hours.
- **Harder to read than `rain_change:v2:split`.** 20 inputs in two groups, some of them overlapping (two ICON windows and the sum to the lead), so single coefficients mean less.
- **Chosen from 68 candidates on inner splits** (plus 4 reference models, 72 rows in the CSV), see `analysis/model-evaluation/models-v2-candidates.csv`. The live shadow run is the clean test.
