# Learnings

What we learned about the models and the way we evaluate them. What we learned about the data itself is in [preliminary-data-analysis.md](../preliminary-data-analysis.md). Append-only: add a new dated section at the end, don't rewrite old ones. If a later finding changes an earlier one, say so in the new section.

The ridge and simple-model numbers come from PRs #68 and #70 before merge. Scores come from the frozen dataset of 2026-10-14 (`eval.parquet`, 19,248 issue times, 2024-02-01 to 2026-04-12) and the folds in [decision 0008](../../docs/decisions/0008-model-evaluation-and-selection.md). MAE is in cm, pooled over the four test folds unless a fold is named. "High water" means the level is above 75 cm at the issue time or at the target.

## 2026-10-14 · Baselines and first models

### Where persistence fails

- **Calm hours dominate the row count.** Persistence: 0.66 cm at +1 h and 4.01 cm at +24 h over all issue times, but 1.36 and 12.99 cm at high water.
- **Rising water carries 46 % of persistence's error at +24 h** (target more than 3 cm above the last level), though it is only 1,702 of 13,081 rows. Calm rows carry only 20 %. Every rain-free model misses a rise by its full height: about −35 cm at the onset of a flood from +6 h on.
- **Persistence never warns of a real crossing.** Its two "24-hour warnings" at 95 cm were re-crossings while the level was still high from the previous flood.
- **Persistence misses peaks by −28 cm at +6 h and −38 cm at +24 h on average** over the 8 events (medians −21 and −31).
- **The lag check works as intended:** persistence's best shift equals its lead.

### Models so far

| Model | All +6 | All +24 | High water +6 | High water +24 |
|---|---|---|---|---|
| persistence | 2.05 | 4.01 | 5.39 | 12.99 |
| recession | 2.05 | 4.01 | 4.83 | 11.48 |
| damped trend | 2.05 | 4.04 | 5.26 | 13.09 |
| upstream | 1.85 | 3.97 | 4.55 | 12.79 |
| ridge, change | 1.88 | 3.18 | 3.94 | 8.36 |
| ridge, change, no ICON | 2.01 | 4.64 | 4.59 | 12.39 |
| rain_change:split | 1.80 | 2.98 | 3.76 | 7.60 |

- **Even day-old, ICON-D2 is the strongest input.** Its sum over hours 1..k alone explains about half of the high-water variance of the change at +6 h and +24 h (R² 0.49 and 0.54). Ridge without it is no better than persistence at +24 h.
- **Upstream is best at +1 h** (0.60 cm) and nothing beats it there yet.
- **Recession helps at high water at long leads** but costs a little on calm rows.
- **The damped trend only helps at +1 h.** Its factor turns negative after about 12 hours: a rise is followed by a fall.
- **Predict the change, not the level, for short leads.** Ridge on the level target loses at +1 h because shrinkage pulls the weight on the last level towards zero; the change target shrinks towards persistence instead.
- **A small model with rain matches ridge.** `rain_change` predicts the change per lead from 6 inputs and a constant: distance to the 30-day base, the 3-hour changes at Langenberg and Nierenhof, radar rain over the last 3 hours and 3–12 hours back, and the ICON-D2 sum over hours 1..k. The `:split` variant fits separate coefficients for rising and other rows. It beats persistence and upstream in all four folds; against ridge it wins F1 clearly and loses F2–F4 narrowly. At +24 h it is 1.04 cm better than persistence (90 % interval −1.31 to −0.78). It warns 7 of 8 crossings of 95 cm, 13 hours ahead in the median, but only 1–2 hours ahead for the four F1 crossings and 13–24 hours for those in F2. Upstream warns all 8, but only 2 hours ahead in the median. The code is still in a scratch analysis, not in the repo.
- **The constant matters.** Without it `rain_change` lost to persistence in a dry period: the rain terms push up on average, and the constant pulls back.
- **Not useful so far:** ICON p90 instead of the mean, radar sums over 12–72 hours, 1-hour upstream changes, rain × level interactions.
- **Alpha for ridge is unstable** between folds (1 to 10,000), and the time-of-year features extrapolate badly when a fold trains on less than a year (F1).

### Evaluation itself

- **Counting misses per lead favours persistence.** It scores "hits" by staying high through a long flood. `rain_change:split` misses 72 lead-hours at 95 cm (summed over the 24 leads) against persistence's 58, but warns far earlier. A miss count per real crossing would judge warnings fairly.
- **All 8 flood episodes above 95 cm fall in F1 and F2;** F3 and F4 have none. Only one episode passes 145 cm (2024-11-19, peak 165 cm). High-water conclusions rest on few events.
- **Any choice made on the test folds is selection on them.** Ridge's alpha grid was set after looking at the folds once; `rain_change` was chosen from about 20 candidates on inner splits that overlap earlier test periods. Design on an inner time split inside the training period and run each finalist through the folds once. The live shadow run is the only clean hold-out.

### Traps we hit

- **Hand models the inputs only.** The harness first passed target columns to `predict`; a model that takes "all numeric columns" would have copied the answer.
- **Score only rows where both forecasts exist.** A NaN prediction once kept persistence's error and pulled the skill from 0.5 to 0.83.
- **Read settings from the dataset's manifest, not today's config,** so a later config change can't silently change a run.
- **Split validation by sorted time,** never by row position.
- **A run with persistence alone must still score.** The bootstrap failed on it the first time.
- **`uv run` drops dependency groups it isn't told about.** Every evaluation command needs `--group analysis`, or pyarrow is gone and Parquet fails.
- **lightgbm needs libgomp in the Lambda image** and `libomp` on macOS.

## 2026-10-14 · Warnings, counted per crossing

Counted with the crossing metric from PR #73: a crossing is warned if a forecast issued before it showed a crossing within 6 hours of it; re-crossings within 24 hours of an earlier flood are left out; a false alarm is a forecast crossing with no observed crossing within ±6 hours. The test folds hold 6 first crossings of 95 cm and 1 of 145 cm, and none above.

| Model | 95 cm warned ≥ 3 h | ≥ 6 h | False alarms per month (95 cm) | 145 cm warned ≥ 3 h |
|---|---|---|---|---|
| persistence | 0 of 6 | 0 | 0.00 | 0 of 1 |
| recession | 0 | 0 | 0.00 | 0 |
| damped trend | 0 | 0 | 0.27 | 0 |
| upstream | 1 | 0 | 0.38 | 1 |
| ridge, level | 2 | 2 | 0.49 | 1 |
| ridge, change | 3 | 1 | 0.38 | 1 |
| rain_change, both variants | 2 | 2 | 0.54 | 0 |

- **Corrects the first section's warning claim.** "7 of 8 crossings warned, 13 hours ahead in the median" for `rain_change` counted re-crossings, 1–2 hour warnings and forecasts that flickered. Per first crossing with at least 3 hours lead it is 2 of 6.
- **No model warns reliably yet.** The best, ridge on the change target, warns half the crossings at least 3 hours ahead. No model warns the 165 cm flood of 2024-11-19 at 145 cm more than 3 hours ahead.
- **Warning earlier costs false alarms.** Every model that warns at all raises about 0.3–0.5 false alarms a month at 95 cm. Persistence never warns, so it never raises one.
- **Too few crossings to rank models.** One flood more or less changes the order. Warnings are reported, not used to select, until we have analysed them and agreed how many false alarms are acceptable.
