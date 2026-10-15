# Learnings

What we learned about the models and the way we evaluate them. What we learned about the data itself is in [preliminary-data-analysis.md](../preliminary-data-analysis.md). Append-only: add a new dated section at the end, don't rewrite old ones. If a later finding changes an earlier one, say so in the new section.

The ridge and simple-model numbers come from PRs #68 and #70 before merge. Scores come from the frozen dataset of 2026-10-14 (`eval.parquet`, 19,248 issue times, 2024-02-01 to 2026-04-12) and the folds in [decision 0008](../../docs/decisions/0008-model-evaluation-and-selection.md). MAE is in cm, pooled over the four test folds unless a fold is named. "High water" means the level is above 75 cm at the issue time or at the target.

## 2026-10-14 · Baselines and first models

### Where persistence fails

- **Calm hours dominate the row count.** Persistence: 0.66 cm at +1 h and 4.01 cm at +24 h over all issue times, but 1.36 and 12.99 cm at high water.
- **Rising water carries 46 % of persistence's error at +24 h** (target more than 3 cm above the last level), though it is only 1,702 of 13,081 rows. Calm rows carry only 20 %. Every rain-free model misses a rise by its full height: about −35 cm at the onset of a flood from +6 h on.
- **Persistence misses peaks by −24 cm at +6 h and −38 cm at +24 h on average** over the 13 flood events (medians −15 and −24).
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
- **A small model with rain matches ridge.** `rain_change` predicts the change per lead from 6 inputs and a constant: distance to the 30-day base, the 3-hour changes at Langenberg and Nierenhof, radar rain over the last 3 hours and 3–12 hours back, and the ICON-D2 sum over hours 1..k. The `:split` variant fits separate coefficients for rising and other rows. It beats persistence and upstream in all four folds; against ridge it wins F1 clearly and loses F2–F4 narrowly. At +24 h it is 1.04 cm better than persistence (90 % interval −1.31 to −0.78). The code is still in a scratch analysis, not in the repo.
- **The constant matters.** Without it `rain_change` lost to persistence in a dry period: the rain terms push up on average, and the constant pulls back.
- **Not useful so far:** ICON p90 instead of the mean, radar sums over 12–72 hours, 1-hour upstream changes, rain × level interactions.
- **Alpha for ridge is unstable** between folds (1 to 10,000), and the time-of-year features extrapolate badly when a fold trains on less than a year (F1).

### Evaluation itself

- **Counting misses per lead favours persistence.** It scores "hits" by staying high through a long flood. `rain_change:split` missed more lead-hours above 95 cm than persistence, though it saw floods coming far earlier. Scores per flood event judge this fairly.
- **13 flood events in the test folds, 6 of them above 95 cm, all in F1 and F2.** F4's five events stay below 95 cm, F3 has one. Only one passes 145 cm (2024-11-19, peak 165 cm). High-water conclusions rest on few events.
- **Any choice made on the test folds is selection on them.** Ridge's alpha grid was set after looking at the folds once; `rain_change` was chosen from about 20 candidates on inner splits that overlap earlier test periods. Design on an inner time split inside the training period and run each finalist through the folds once. The live shadow run is the only clean hold-out.

### Traps we hit

- **Hand models the inputs only.** The harness first passed target columns to `predict`; a model that takes "all numeric columns" would have copied the answer.
- **Score only rows where both forecasts exist.** A NaN prediction once kept persistence's error and pulled the skill from 0.5 to 0.83.
- **Read settings from the dataset's manifest, not today's config,** so a later config change can't silently change a run.
- **Split validation by sorted time,** never by row position.
- **A run with persistence alone must still score.** The bootstrap failed on it the first time.
- **`uv run` drops dependency groups it isn't told about.** Every evaluation command needs `--group analysis`, or pyarrow is gone and Parquet fails.
- **lightgbm needs libgomp in the Lambda image** and `libomp` on macOS.

## 2026-10-15 · Flood scores per event

- **Warnings per threshold crossing were hard to read and blind to most floods.** Matching forecast and observed crossings of 95 cm within ±6 hours, leaving out re-crossings and counting the earliest forecast that flickered, gave counts few people could follow. They covered only the 6 floods above 95 cm, all in winter 2024/25. Replaced by flood forecasts per event ([evaluation.md](../../docs/evaluation.md#flood-forecasts)): for each of the 13 events, did a forecast 24, 12, 6, 3 and 1 hour before the peak see more than half the rise, how much of it, and how many hours off.
- **No model warns reliably yet.** Under the old crossing rule, no model got more than half of the 95 cm crossings 3 hours ahead, and none warned the 165 cm flood of 2024-11-19 at 145 cm more than 3 hours ahead. The new scores follow with the next run.
- **Warning earlier costs false alarms.** Every model that warned at all raised false alarms; persistence never warns, so it never raises one. False alarms stay the counterweight in the new scores.
