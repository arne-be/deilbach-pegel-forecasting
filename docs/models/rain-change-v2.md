# Rain change model, version 2

`rain_change:v2:split` forecasts the Kupferdreh level 1 to 24 hours ahead as the last cleaned level plus a change. The change is a straight line in a short list of named inputs, fitted separately for each lead and separately for rising and other rows. It is [`rain_change:split`](rain-change.md) plus four things the [learnings](../../analysis/model-evaluation/learnings.md) pointed to. Code: `src/pegel/evaluation/models/curated.py` (`RAIN_CHANGE_V2`), inputs in `src/pegel/core/features.py`.

It is a backtest model for now, like version 1.

## Inputs, and why each one

The seven inputs of version 1 stay: a constant, the distance to the 30-day base, the 3-hour changes at Langenberg and Nierenhof, radar rain over the last 3 hours and 3 to 12 hours back, and the ICON-D2 mean summed over hours 1 to k. Added:

1. **The recent rise, faded by its age.** The rise of the last day (highest minus lowest of the last level and the 24 hourly lags) times exp(−hours since the peak / 24 h). The age of a lag is counted about an hour too long, which the coefficients absorb. A rise still going on counts in full; a peak a day ago counts about a third. Its coefficient is negative at every lead: what went up comes down. The data analysis suggested a fast recession with a time constant of 6 to 8 hours, counted only after the peak. On the inner splits a version gated to after the peak was worse, and 24 hours beat 6, 8, 12, 36 and 48. So this is less a recession curve than a measure of how big and how fresh the last event is.
2. **Kupferdreh's own 3-hour change, counted from the newest reading.** Lag 0 was never known before 2024-11-20 and known at 98–99 % of issue times after, so the change pairs the newest reading with the lag 3 hours older than it, whatever its age. Version 1 used lag 0 only for the rising split and fitted F1 without it.
3. **ICON-D2 above 5 mm.** max(sum over hours 1..k − 5 mm, 0). The analysis found the rise roughly linear in rain, with a hinge near 5 mm only a candidate. On the inner splits it helped the long leads.
4. **A summer daily cycle.** Sine and cosine of the issue hour and of twice the issue hour, set to 0 from October to March. The level dips by 6 to 8 cm in the early afternoon on summer days. With a coefficient per lead the four terms can shift the forecast to the right time of day.

The rising split is the same as in version 1 (Kupferdreh or Langenberg up more than 0.5 cm in 3 hours), but the Kupferdreh change is now the age-aligned one.

## Formula

For lead k and each of the two row groups:

```
level_k  = last + change_k
change_k = c0 + c1·(last − base_30d)
              + c2·Langenberg 3 h change + c3·Nierenhof 3 h change
              + c4·radar, lags 0–2 + c5·radar, lags 3–11
              + c6·ICON-D2 sum 1..k + c7·max(ICON-D2 sum 1..k − 5, 0)
              + c8·recent rise, faded over 24 h
              + c9·Kupferdreh 3 h change
              + c10..c13·summer hour terms
```

## Fitting

Ordinary least squares per lead and group on the change (`target_k − last`), on every training row with a target and all inputs for that lead.

## Missing inputs

- A missing upstream change, Kupferdreh change or recent rise counts as 0.
- Anything else missing gives persistence: the last level for every lead.

## Typical coefficients

Fitted on the training rows of fold F4 (2024-02-01 to 2025-09-29), in cm per cm or cm per mm:

| Group, lead | Constant | To base | Langenberg | Nierenhof | Radar 0–2 | ICON sum | ICON > 5 mm | Recent rise | KD 3 h change |
|---|---|---|---|---|---|---|---|---|---|
| rising, +1 h | 0.18 | −0.03 | 0.25 | 0.49 | 0.22 | 0.44 | 0.75 | −0.07 | −0.11 |
| rising, +6 h | 0.95 | −0.05 | 0.31 | 0.65 | 0.66 | 1.06 | 0.08 | −0.27 | −0.31 |
| rising, +24 h | 0.09 | −0.09 | 0.13 | 0.43 | −0.13 | 0.86 | 0.30 | −0.44 | −0.32 |
| other, +1 h | −0.09 | 0.00 | 0.22 | 0.44 | 0.25 | 0.45 | −0.73 | −0.07 | −0.41 |
| other, +6 h | −0.39 | −0.03 | 0.49 | 0.71 | 0.66 | 0.77 | 0.29 | −0.16 | −0.62 |
| other, +24 h | −1.30 | −0.09 | 1.27 | 1.61 | −0.68 | 0.64 | 0.74 | −0.16 | −0.27 |

With the recent rise in the model, the distance to the base matters less than in version 1 (−0.09 at +24 h instead of −0.16).

## Results

From one run on the frozen dataset of 2026-10-14 (19,248 issue times), the four folds of [decision 0008](../decisions/0008-model-evaluation-and-selection.md). MAE in cm, pooled over the folds. High water: above 75 cm at the issue time or at the target.

| Model | All +1 | All +6 | All +12 | All +24 | All, mean | High water +6 | High water +24 | High water, mean |
|---|---|---|---|---|---|---|---|---|
| persistence | 0.66 | 2.05 | 3.03 | 4.01 | 2.84 | 5.39 | 12.99 | 8.25 |
| ridge:change | 0.70 | 1.88 | 2.70 | 3.18 | 2.46 | 3.94 | 8.36 | 5.60 |
| rain_change:split | 0.66 | 1.80 | 2.53 | 2.98 | 2.31 | 3.76 | 7.60 | 5.22 |
| **rain_change:v2:split** | 0.67 | 1.55 | 2.19 | 2.84 | 2.07 | 3.68 | 7.45 | 5.10 |

Per fold, mean MAE over leads 1 to 24, all issue times:

| Fold | ridge:change | rain_change:split | rain_change:v2:split |
|---|---|---|---|
| F1 | 3.730 | 2.506 | 2.388 |
| F2 | 1.716 | 1.799 | 1.718 |
| F3 | 2.727 | 2.730 | 2.365 |
| F4 | 1.932 | 2.034 | 1.784 |

It beats `rain_change:split` in all four folds and `ridge:change` in three (F2 is a tie, 0.002 cm behind). The pooled high-water MAE is lower than both, so under the selection rule of decision 0008 it wins over both. At +24 h it is 1.18 cm better than persistence (90 % bootstrap interval −1.45 to −0.93 cm). The biggest gains are at +6 to +12 h and in the summer fold F3, where the daily cycle term does its work.

**Warnings at 95 cm** (crossing metric, 6 first crossings): 2 warned at least 3 and at least 6 hours ahead, the same as version 1. 0.38 false alarms a month instead of 0.54. The 145 cm crossing of 2024-11-19 is not warned 3 hours ahead.

## Known weaknesses

- **No gain at +1 h.** 0.67 cm, persistence 0.66, upstream 0.60.
- **Still too low at high water.** Bias −1.48 cm at +6 h and −3.65 cm at +24 h (version 1: −1.82 and −3.92, persistence −0.80 and −3.03). Rises are still caught late.
- **Warnings did not improve.** Two of six crossings get 3 hours or more.
- **High water is worse than version 1 in F3** (9.89 against 9.36 cm, mean over leads), a fold with almost no high water.
- **Chosen from 68 candidates on inner splits** (plus 4 reference models, 72 rows in the CSV). See the PR and `analysis/model-evaluation/models-v2-candidates.csv`. The inner splits of later folds overlap earlier test periods, and the data analysis behind the ideas covered the whole window. The live shadow run is the clean test.
- **Trained on day-old ICON-D2**, as version 1.
