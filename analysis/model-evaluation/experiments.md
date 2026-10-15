# Experiment log

Every scored run of the model evaluation gets one section here (docs/decisions/0008). The log
holds the runs of the current evaluation method only, so every section compares the same way.
Within a method it is append-only: earlier sections are never edited, and a later run that
changes a conclusion says so in its own section. When the method changes, the log starts
again with a fresh run; older runs stay in git history.

The method changed on 2026-10-15 (flood events from fast rises, flood forecasts per event).
No run with it yet: the scorer and the report still write the old warning tables. The first
run follows once they are updated.

## How to read this

Each section starts with a short summary, the notes and one table with a row per model. The
plots follow; the detail tables and the plot per flood are folded below them. Plots live in
`plots/<run>/`. The full rules are in [docs/evaluation.md](../../docs/evaluation.md).

- **MAE:** mean absolute error of the forecast level in cm, pooled over the four test folds.
  "Mean MAE" averages the leads 1 to 24 hours.
- **Skill:** 1 - MAE / MAE of persistence on the same rows. Persistence is 0; above 0 is
  better than holding the last level.
- **High water:** issue times where the cleaned level is above `evaluation.high_water_cm`
  (75 cm) at the issue time or at the target. Every score uses only the cleaned Kupferdreh
  series, never the raw one.
- **Flood forecasts:** for each of the 13 flood events and each lead of 24, 12, 6, 3 and 1
  hours before the peak, the forecast issued then. **Size** is the share of the rise from the
  pre-event level it saw, **timing** how many hours its peak was off, and **predicted** means
  it saw more than half the rise.
- **False alarm:** a forecast that shows a new event while none is running or starts within
  24 hours. A run of such forecasts counts once; the rate is per test month.

## Adding a run

With a frozen dataset `eval.parquet` and a run folder named after the date and what it tries,
from the repo root:

```
uv run --group analysis python -m pegel.evaluation.predict <eval.parquet> --out <runs>/<run> [--models a,b]
uv run --group analysis python -m pegel.evaluation.score <runs>/<run>/predictions.parquet <eval.parquet> --out <runs>/<run>
uv run --group analysis python -m pegel.evaluation.report <runs>/<run> --notes "what was tried, what we learned"
```

The last command writes the plots and appends the section. Commit both.
