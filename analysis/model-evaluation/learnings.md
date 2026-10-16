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

## 2026-10-15 · First run with flood scores per event

From run [2026-10-15-flood-scores](experiments.md#2026-10-15-flood-scores).

- **The v2 models gain most 6 to 24 hours before the peak.** 6 hours before, both see all 13 floods, persistence 8 and `upstream` 10; 24 hours before, 8 and 9 against 5. At 3 and 1 hour every model sees almost all of them, so those leads don't tell models apart.
- **Persistence's 5 floods a day ahead are not foresight.** All five (events 4, 7, 9, 10, 12) started from a level already high from an earlier peak, and persistence's own peak is at the issue time (timing −23 h). Read its 24 h count as the floor that slow, multi-peak events give for free.
- **The biggest flood is missed a day ahead by every model.** On 2024-11-19 (165 cm) all four saw at most 32 % of the rise 12 and 24 hours before, because ICON-D2 badly underforecast the rain. Only once the rain had fallen (6 hours before) did the v2 models see 76 to 80 %. Fresher ICON-D2 runs live may help here; the backtest can't tell.
- **The same rain inputs overshoot small floods.** On 2026-02-22 (91 cm, from 70 cm) the v2 models forecast 145 to 162 % of the rise 12 hours ahead; even 1 hour before, the median over all 13 floods is 5 to 8 % above the rise (up to 127 % on 2024-12-06). A rise of 21 cm makes any overshoot large in relative terms.
- **False alarms are rare under the new rule:** 2 (`rain_change:v2:split`) and 3 (`ridge:change:v2`) in 18 test months, `upstream` 1, persistence none. The extra flood `ridge:change:v2` sees a day ahead (event 8) costs about one false alarm.

## 2026-10-15 · LightGBM on the ridge residual

From run [2026-10-15-lightgbm-residual](experiments.md#2026-10-15-lightgbm-residual).

- **Trees on the ridge residual don't beat ridge.** Plain and `linear_tree` variants lose over all issue times in 2 and 3 of 4 folds, by up to 0.13 cm (F1). Ridge seems to take what these inputs hold; the rest looks like noise and ICON-D2 error.
- **The trees mostly learned season.** Season sine and cosine carry a third of the gain. With 8 to 20 months of training, each season is seen once or twice, so the correction is drift of those months, not a rule. F1 (trained Feb to Sep, tested Oct to Dec) loses most.
- **The residual correction is safe for floods.** Flood size held and false alarms stayed below 0.25 per month (4 and 3 against ridge's 3), and the high-water bias at +24 h shrank from −3.8 to −3.2 cm. The cap on the trees did what was hoped: it limited only the correction.
- **In-sample ridge residuals are too small to train on.** They were 8 to 33 % below out-of-fold ones on the inner splits, more at high water and long leads. Any model stacked on ridge needs out-of-fold residuals.
- **The inner split wanted almost no boosting:** 10 rounds at a learning rate of 0.05. That alone says the residual holds little a tree can use with these inputs.

## 2026-10-15 · Capped training: floods beyond the training range

From run [2026-10-15-capped-training](experiments.md#2026-10-15-capped-training). Each `:cap100` model is trained without any issue time whose cleaned level or any target is above 100 cm, so the four test floods above 100 cm (121, 165, 125 and 105 cm) are bigger than anything in training.

- **The linear change models extrapolate well enough.** No family loses more than 20 points of flood size, the agreed mark for "unfit for new record floods". The largest loss is 13 points (`rain_change:v2:split`, the 125 cm flood 12 hours before: 58 → 45 %); `ridge:change:v2` loses up to 10 points on the same flood. On the 121 and 165 cm floods the capped models are within 3 points of the uncapped ones.
- **`upstream` doesn't care.** Its two factors per lead barely move, so its sizes match within 3 points and its high-water MAE is unchanged.
- **High-water MAE rises a little for the v2 models:** about +0.1 cm at +1 h and +0.2 cm from +12 h, mean +0.2 cm over leads 1 to 24 h. They still beat persistence in all four folds.
- **Persistence is identical capped and uncapped,** which checks that the wrapper filters training only.
- **Caveat:** the cap also drops the rising limbs into big peaks, which carry most of the signal for rain coefficients. Read the losses as a comparison between families, not as what a real record flood would cost. A tree model (LightGBM), which can't go beyond its training range, is the case this test is meant for; it isn't in this run.

## 2026-10-15 · Rain response from a unit hydrograph

From run [2026-10-15-rain-response](experiments.md#2026-10-15-rain-response).

- **A hydrograph fitted on radar doesn't make big floods bigger.** Events 1, 2 and 6 (121, 165 and 125 cm) get 0 to 3 points more of their rise a day ahead than with `ridge:change:v2`, and their peaks stay 5 to 7 hours late 6 and 12 hours ahead. A day ahead the rain hasn't fallen, so the radar part can't help, and the ICON part is shrunk like the ICON sum was.
- **The ridge keeps ICON at about half the radar gain.** Its coefficient on the ICON response is 0.34 to 0.58 in every fold and lead, so the regression dilution of day-old ICON stays whether the input is a sum or a convolution.
- **At its fitted gain the radar response is too strong.** Added as a fixed offset it loses to `ridge:change:v2` in all four folds, is biased +0.4 cm at +24 h and doubles the false alarms (6 in 18 months). Given to the ridge, its weight drops to about 0.5 at +6 h and 0 at +24 h, where `recent_rise` and the Kupferdreh change already carry the recession.
- **Fit the slow store on more than a day.** On the 24-hour change the slow store's time constant runs to the edge of any grid, because over a day it looks like a step. On 72 hours it settles at 96 to 144 h, with the fast store at 4 to 6 h and the peak 4 to 5 h after the rain, close to the analysis.
- **As a ridge input the responses are a fair swap for the radar and ICON sums:** 2.06 against 2.07 cm over all issue times, 4.74 against 4.83 cm at high water, the same false alarms. Small enough to be selection noise. Both variants are retired; the code is in git history (see [models.md](../../docs/models.md#retired)).
- **A day ahead the limit is ICON quality, not model form or training range.** Inside the ridge variant the ridge gives the ICON response 0.34 to 0.58 of the radar gain, and the radar response about 0 at +24 h. However the rain enters, as sums or through a physical hydrograph, the model can only trust day-old ICON about half, and a day ahead there is nothing else to go on.

## 2026-10-16 · Uncertainty bands

Bands for `ridge:change:v2` from its out-of-sample errors in run 2026-10-15-models-v2. Three schemes were proposed, attacked by three critics (statistics, live operation, flood safety) and judged. All calibrated forward: F2 on F1, F3 on F1–F2, F4 on F1–F3.

- **One table per lead undercovers exactly where it matters.** At +24 h its 80 % band holds 58 % on rainy issue times and 95 % on dry ones. Pooled over leads it looks fine (77 %).
- **A continuous scale beats situation buckets.** Scaling the error by the predicted change and the ICON rain wins in every fold and in 63 of 69 weeks (interval score at 90 %: 11.8 against 18.2 for the per-lead table). Buckets from hydrology (15.1) or a shallow tree (14.3) won less, and their rare cells (strong rise, elevated level) rested on 6 to 20 episodes, with tails that moved threefold under bootstrap.
- **The model's own predicted change is the best single input** for how wrong it will be. Every scheme found it.
- **Keep the ICON term.** Without it, 31 % of readings on rises into a flood land above the 95 % band; with it, 14 %. Its cost in coverage showed up only in folds calibrated without a summer.
- **A missing input must not look calm.** One missing radar or ICON hour turns the curated models into persistence. With the scaled table that gives 59 % coverage at 90 %, with persistence errors 93 %. The eval set has no such rows, so this was simulated.
- **Not solved:** 14 % of into-flood readings above the 95 % band (nominal 2.5 %); a summer calibrated on winters undercovers (F3 83 % at 90 %); bands jump up to 13 cm between hours.
