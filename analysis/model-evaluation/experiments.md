# Experiment log

Every scored run of the model evaluation gets one section here (docs/decisions/0008). The log
is append-only: earlier sections are never edited. A later run that changes a conclusion says
so in its own section. Plots live in `plots/<run>/`.

To add a run, with a frozen dataset `eval.parquet` and a run folder named after the date and
what it tries, from the repo root:

```
uv run --group analysis python -m pegel.evaluation.predict <eval.parquet> --out <runs>/<run> [--models a,b]
uv run --group analysis python -m pegel.evaluation.score <runs>/<run>/predictions.parquet <eval.parquet> --out <runs>/<run>
uv run --group analysis python -m pegel.evaluation.report <runs>/<run> --notes "what was tried, what we learned"
```

The last command writes the plots and appends the section. Commit both.

Tables: MAE in cm, pooled over the four folds. Skill is 1 - MAE / MAE of persistence on the
same rows, so persistence is always 0. Subsets: `all` issue times; `high_water` where the
cleaned level is above `evaluation.high_water_cm` at the issue time or at the target;
`high_water_raw` the same by the raw level, scored against the raw target.

## 2026-10-14-persistence

- Run: 2026-10-14, commit `15cfa3e02744` (clean)
- Dataset sha256: `aca86a175c82e3eb89602d018bea7bba044b8755d085e05ec92032d2f367407f`
- Models: persistence

### MAE in cm, pooled over folds

Subset `all`:

| model | +1 h | +3 h | +6 h | +12 h | +24 h | mean 1-24 h | mean skill |
|---|---|---|---|---|---|---|---|
| persistence | 0.66 | 1.32 | 2.05 | 3.03 | 4.01 | 2.84 | 0.00 |

Subset `high_water`:

| model | +1 h | +3 h | +6 h | +12 h | +24 h | mean 1-24 h | mean skill |
|---|---|---|---|---|---|---|---|
| persistence | 1.36 | 3.15 | 5.39 | 8.57 | 12.99 | 8.25 | 0.00 |

Subset `high_water_raw`:

| model | +1 h | +3 h | +6 h | +12 h | +24 h | mean 1-24 h | mean skill |
|---|---|---|---|---|---|---|---|
| persistence | 2.10 | 3.85 | 6.04 | 9.14 | 13.48 | 8.83 | 0.00 |

### Alarms

Flood episodes per threshold: hits / misses / false alarms of the lead-k forecasts.

| model | threshold_cm | +1 h | +6 h | +12 h | +24 h |
|---|---|---|---|---|---|
| persistence | 95.00 | 7 / 1 / 1 | 7 / 1 / 3 | 6 / 2 / 4 | 5 / 3 / 5 |
| persistence | 145.00 | 1 / 0 / 0 | 0 / 1 / 1 | 0 / 1 / 1 | 0 / 1 / 1 |

### Warnings

Observed crossings and the first forecast that showed them. A re-crossing starts while the level was above the threshold in the 24 hours before; its warning is not counted as lead time.

| model | threshold_cm | crossings | warned | median hours ahead | min hours ahead | re-crossings | re-crossings warned |
|---|---|---|---|---|---|---|---|
| persistence | 95.00 | 6 | 0 | - | - | 2 | 2 |
| persistence | 145.00 | 1 | 0 | - | - | 0 | 0 |

### Peaks

Forecasts issued k hours before each flood peak: highest value minus peak, value at the peak minus peak, and timing of the highest value (positive is late).

| model | lead | events | mean abs height error (cm) | mean at-peak error (cm) | mean timing error (h) |
|---|---|---|---|---|---|
| persistence | 6 | 8 | 27.60 | -27.60 | - |
| persistence | 12 | 8 | 36.86 | -35.84 | - |

### Lag check

Shift in hours that best matches the forecast to the observed level on high water.

| model | shift at +6 h | shift at +12 h |
|---|---|---|
| persistence | 6 | 12 |

### Plots

![mae](plots/2026-10-14-persistence/mae.png)
![mae-folds](plots/2026-10-14-persistence/mae-folds.png)
![event-1-2024-10-10](plots/2026-10-14-persistence/event-1-2024-10-10.png)
![event-2-2024-11-19](plots/2026-10-14-persistence/event-2-2024-11-19.png)
![event-3-2024-12-06](plots/2026-10-14-persistence/event-3-2024-12-06.png)
![event-4-2024-12-22](plots/2026-10-14-persistence/event-4-2024-12-22.png)
![event-5-2025-01-05](plots/2026-10-14-persistence/event-5-2025-01-05.png)
![event-6-2025-01-08](plots/2026-10-14-persistence/event-6-2025-01-08.png)
![event-7-2025-01-26](plots/2026-10-14-persistence/event-7-2025-01-26.png)
![event-8-2025-01-27](plots/2026-10-14-persistence/event-8-2025-01-27.png)

**Notes:** Persistence MAE 0.66 cm at +1 h and 4.01 cm at +24 h over all issue times; 1.36 cm at +1 h and 12.99 cm at +24 h at high water. At 95 cm it hits 7 of 8 flood episodes at +1 h and 5 of 8 at +24 h, with 5 false alarms at +24 h; the one episode above 145 cm (2024-11-19) is hit at +1 h to +5 h and missed from +6 h on. It warns ahead of none of the 6 first crossings of 95 cm; its two warnings are re-crossings (2025-01-08, 2025-01-27). Peaks are underforecast by 27.6 cm at +6 h and 36.9 cm at +12 h on average; the lag check gives a shift equal to the lead. All 8 flood episodes fall in F1 and F2. No bootstrap band and no skill plot: the run has only persistence.
