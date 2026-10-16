# Models

Every model the evaluation runs, what it does and why. How models are scored is in [evaluation.md](evaluation.md), the plan behind the ladder in [decision 0008](decisions/0008-model-evaluation-and-selection.md). The website shows `ridge:change:v2` ([In production](#in-production-ridgechangev2)); every other model is a backtest model. The registered list is `src/pegel/evaluation/registry.py`.

## Ladder

Mean MAE in cm over leads 1 to 24, pooled over the four folds, from run [2026-10-15-flood-scores](../analysis/model-evaluation/experiments.md#2026-10-15-flood-scores). High water: above 75 cm at the issue time or at the target. Floods seen 24 h ahead: of the 13 flood events, how many the forecast issued 24 hours before the peak saw more than half the rise of ([evaluation.md](evaluation.md#flood-forecasts)).

| Model | Idea | All | High water | Floods seen 24 h ahead | Code |
|---|---|---|---|---|---|
| `persistence` | the last level for every lead; the baseline | 2.8 | 8.3 | 5 | `models/persistence.py` |
| `upstream` | Langenberg and Nierenhof 3-hour changes, no constant; the best at +1 h | 2.7 | 7.8 | 5 | `models/simple.py` |
| **`rain_change:v2:split`** | 14 named inputs | 2.1 | 5.1 | 8 | `models/curated.py` |
| **`ridge:change:v2`** | 20 named inputs, ridge penalty | 2.1 | 4.8 | 9 | `models/curated.py` |
| `lgbm_residual:v1` | LightGBM on the residual of `ridge:change:v2`; ruled out | 2.1 | 4.8 | 10 | `models/residual.py` |
| `lgbm_residual:v1:linear` | the same with `linear_tree`; ruled out | 2.1 | 4.9 | 10 | `models/residual.py` |

The two v2 models are the current best. Under the selection rule both win over `rain_change:split` and `ridge:change` (`rain_change:v2:split` ties `ridge:change` in F2 and wins on high water). They are level over all issue times, and `ridge:change:v2` is better at high water and sees one flood more a day ahead, but has one false alarm more (3 against 2 in 18 test months).

All learned models forecast the **change** from the last cleaned level, one fit per lead (1 to 24 hours), so the forecast is `last + change_k`. `upstream` falls back to persistence when an upstream change is missing. In the v2 models a missing upstream change, Kupferdreh change or recent rise counts as 0; any other missing input gives persistence. The v2 models are trained on day-old ICON-D2 (see [evaluation.md](evaluation.md#the-icon-d2-archive)).

## Retired

Retired on 2026-10-15, so run outputs show only the models that matter. The code is in git history (last in commit d43bb1b). Numbers as in the ladder above (all, high water).

- `recession`, `damped_trend` (models 2 and 3 of the ladder, in `models/simple.py`): one fitted factor per lead on the distance to the 30-day base or on the Kupferdreh 3-hour change. Close to persistence: 2.8 / 7.4, 2.8 / 8.2.
- `ridge:level`, `ridge:change` (`models/ridge.py`): ridge on about 200 shared feature columns (`core/features.features`), gaps filled with the last known value plus a flag. Beaten by `ridge:change:v2`: 2.7 / 5.6, 2.5 / 5.6.
- `ridge:level:no_icon`, `ridge:change:no_icon`: the same without ICON-D2; no-ICON runs were dropped in decision 0008. 3.4 / 8.4, 3.1 / 7.7.
- `rain_change`, `rain_change:split` (`models/rain_change.py`): the 7 v1 inputs (the first six rows of the table below), plain least squares. Beaten by `rain_change:v2:split`: 2.4 / 5.4, 2.3 / 5.2.

With them went the shared ridge features (`features.features`) and the target forms (`evaluation/targets.py`) with the hourly-step features (`features.step_features`), which no remaining model used.

Retired on 2026-10-15 after one run ([2026-10-15-rain-response](../analysis/model-evaluation/experiments.md#2026-10-15-rain-response)), never merged. The code is in git history at commit 7e5e5801c9d9 on branch `feat/rain-response-model` (PR #91; `git fetch origin pull/91/head`).

- `rain_response:v1:offset`, `rain_response:v1:ridge` (idea 1): a two-store unit hydrograph (fast store 4–6 h, slow 96–144 h, peak about 2 cm per mm 4–5 hours after the rain), fitted per fold on radar-only rain episodes. It turned the last 168 hours of radar and the ICON-D2 hours ahead into a level change per lead. The offset variant added the radar response at the fitted gain and lost to `ridge:change:v2` in all four folds (2.2 / 5.1, 6 false alarms). The ridge variant used both responses as ridge inputs and only tied it (2.1 / 4.7). The floods of 120 cm or more got 0 to 3 points more of their rise a day ahead, and their peaks stayed 5 to 7 hours late.

## Rain change

The Deilbach catchment is small and reacts within hours. Langenberg leads Kupferdreh by about 1 hour, Nierenhof by about 0 hours and radar rain by about 1 hour, all fading after about 4 hours. So a few inputs close to the issue time are enough, each with a physical reason:

| Input | Why | v2 | ridge v2 |
|---|---|---|---|
| constant | rain terms push up on average; the constant pulls back. Without it the model lost to persistence in a dry period | ✓ | ✓ |
| last − 30-day base | high water falls back towards normal | ✓ | ✓ |
| Langenberg, Nierenhof 3 h change | the upstream wave, about an hour ahead; a missing change counts as 0 | ✓ | ✓ |
| radar, lags 0–2 | rain that has fallen but not arrived yet | ✓ | ✓ |
| radar, lags 3–11 | old rain: the wave has passed, the water will fall (negative) | ✓ | ✓ |
| ICON-D2 mean, sum over hours 1..k | rain still to fall; the strongest input even day-old | ✓ | ✓ |
| ICON-D2 sum 1..k above 5 mm | a hinge at 5 mm; helped the long leads on the inner splits | ✓ | ✓ |
| recent rise, faded over 24 h | the rise of the last day × exp(−hours since peak / 24); what went up comes down | ✓ | ✓ |
| Kupferdreh 3 h change | the rise or fall now, counted from the newest reading | ✓ | ✓ |
| summer hour terms | the level dips 6 to 8 cm in summer afternoons; sine and cosine of the hour and twice the hour, 0 from October to March | ✓ | ✓ |
| Kupferdreh 1 h change | for the shortest leads | | ✓ |
| recent rise, faded over 6 h | the fast part of the recession | | ✓ |
| radar, lags 12–23 | the longer falling limb | | ✓ |
| ICON-D2 sums 1–6 h and 1–24 h | how much rain is coming soon and in the next day, the same for every lead | | ✓ |
| ICON-D2 sum 1..k × last level / 10 | the same rain gives fewer cm from a high start; coefficient near 0 | | ✓ |

Radar is the catchment mean: the five zone means weighted by their number of radar cells. The `catchment` series in the dataset is the maximum, not the mean, so it isn't used.

**Kupferdreh's change from the newest reading.** At hh:30 the current hour's reading is missing in 38 % of cases (lag 0 was never known before 2024-11-20). So the change pairs the newest reading with the lag 3 hours older than it, whatever its age (`features.kupferdreh_change`).

**The split.** Both v2 models fit two coefficient sets: one for rising rows (Kupferdreh or Langenberg up more than 0.5 cm in 3 hours), one for the rest. For rising rows the constant is near zero or positive up to +6 h: the rise goes on. For the others it is negative, and a falling upstream gauge carries through to +24 h.

**Fitting.** `rain_change:v2:split`: ordinary least squares per lead and group. `ridge:change:v2`: the same with a ridge penalty of 100 on inputs scaled to unit standard deviation, constant not penalised. 100 was chosen on the inner splits from 10 to 1000; 1000 had a slightly lower mean MAE, 100 the lower high-water MAE.

```
change_k = c0 + c1·(last − base_30d)
              + c2·Langenberg 3 h change + c3·Nierenhof 3 h change
              + c4·radar 0–2 + c5·radar 3–11
              + c6·ICON-D2 sum 1..k + …   (v2 inputs from the table)
```

**Typical coefficients**, `rain_change:v2:split` fitted on fold F4's training rows (2024-02-01 to 2025-09-29), in cm per cm or cm per mm:

| Group, lead | Constant | To base | Langenberg | Nierenhof | Radar 0–2 | ICON sum | ICON > 5 mm | Recent rise | KD 3 h change |
|---|---|---|---|---|---|---|---|---|---|
| rising, +1 h | 0.18 | −0.03 | 0.25 | 0.49 | 0.22 | 0.44 | 0.75 | −0.07 | −0.11 |
| rising, +6 h | 0.95 | −0.05 | 0.31 | 0.65 | 0.66 | 1.06 | 0.08 | −0.27 | −0.31 |
| rising, +24 h | 0.09 | −0.09 | 0.13 | 0.43 | −0.13 | 0.86 | 0.30 | −0.44 | −0.32 |
| other, +1 h | −0.09 | 0.00 | 0.22 | 0.44 | 0.25 | 0.45 | −0.73 | −0.07 | −0.41 |
| other, +6 h | −0.39 | −0.03 | 0.49 | 0.71 | 0.66 | 0.77 | 0.29 | −0.16 | −0.62 |
| other, +24 h | −1.30 | −0.09 | 1.27 | 1.61 | −0.68 | 0.64 | 0.74 | −0.16 | −0.27 |

**How the inputs were chosen.** On an inner time split inside each fold's training rows: fit on the older 80 %, validate on the newest 20 %, with a 24-hour gap. Version 1 (retired) came from about 20 candidates, version 2 from 68 (`analysis/model-evaluation/models-v2-candidates.csv`). Tried and dropped: ICON-D2 p90, the radar zones and the catchment maximum, radar beyond 24 hours, Kupferdreh and upstream level lags, a recession gated to after the peak, other time constants (6, 8, 12, 36, 48 h) in place of the 24-hour one in `rain_change:v2:split`. The inner splits of later folds overlap earlier test periods, so this is not a clean hold-out; the live shadow run is.

## In production: `ridge:change:v2`

The website shows `ridge:change:v2`. It ties `rain_change:v2:split` over all issue times, is better at high water (4.8 against 5.1 cm) and sees one flood more a day ahead, at the cost of one false alarm more in 18 test months. Decision: [0009](decisions/0009-ridge-in-production.md).

**Training.** `pegel train-model` fits the model on every issue time from 2024-02-01 to 2026-04-12 with the same code and the same settings as the evaluation (`registry.py`), reading prod read-only. The window ends where the Langenberg open data ends: a missing upstream change counts as 0, so months without Langenberg would teach the model that upstream rises don't matter. Rerun it whenever new data has arrived:

```
JOBS_DATABASE_URL="$(pbpaste)" uv run pegel train-model --model ridge:change:v2 --to <last day> --out ~/data/deilbach-pegel/models/<date>/ --bucket deilbach-pegel-data-<account>
pbcopy </dev/null
```

It prints the coverage of every input, so check that no gauge is missing over long stretches before going further.

**The model file.** One JSON file per training run: the input names, split, ridge penalty, the radar cells per zone and the coefficients (2 groups × 24 leads × 20 inputs), the [band table](#uncertainty-bands), plus what it was trained on: window, row count, code commit, config, database and the in-sample MAE per lead. JSON, not pickle, so a file can't run code when loaded. Loading refuses a file whose radar zones differ from the current cells file or whose coefficients aren't finite. It lives in the data bucket under `models/`, and a file is never overwritten.

**Going live.** `forecast.model_file` in `config/pegel.json` names the file the hourly job loads. A new model goes live by changing that key in a PR; a rollback is the same change back to the previous file. The model only goes live if it beats the current one on the same evaluation (`.claude/rules/data-and-ml.md`).

**Each hour.** At hh:30 the job builds one dataset row for the issue time with the code that builds the evaluation dataset (`eval_set.build_rows`), so training and live inputs can't drift apart. Every input is taken as known at the issue time. The model forecasts leads 1 to 24, and the website shows 24 hours. 48 hours waits for data: the training data has no rain forecast known beyond 24 hours (see [0009](decisions/0009-ridge-in-production.md)). The job saves persistence first and then the ridge forecast. If the ridge step fails, the failure is logged and persistence still gets saved; the API then serves persistence, because it never shows a ridge forecast older than the newest persistence one. The response's `model` field says which one it is. Each input is read only as far back as it needs (30 days for the base level, a day for the gauges, a week for radar), about 0.5 MB per run from Neon. A rerun of a past hour (`pegel run-hourly --issued-at`) usually gets a ridge forecast with persistence values: live readings are stamped with the hour they were fetched, so at a past issue time they weren't known yet, and an unknown input counts as no change.

**What to watch.** It went live without a shadow run, so live forecasts are its first real hold-out. It was trained on day-old ICON-D2 rain, while live values come from runs 4 to 27 hours ahead. Having learned to trust day-old rain little, it may underuse sharp short-range rain live ([catchment.md](catchment.md#what-a-model-sees-at-an-issue-time)). The weaknesses below still apply.

## LightGBM on the ridge residual

Step 6 of the ladder, in a form that keeps ridge's flood size: `ridge:change:v2` makes the forecast, and one LightGBM booster per lead adds a correction fitted on its residual. Ridge is linear and extrapolates; a tree can't go past the residuals it trained on, so its cap limits only the correction. Numbers from run [2026-10-15-lightgbm-residual](../analysis/model-evaluation/experiments.md#2026-10-15-lightgbm-residual).

- **Inputs:** the `ridge:change:v2` inputs without the constant, plus the last level and sine and cosine of the issue hour and of the day of the year.
- **Out-of-fold residuals.** The training rows are cut into 3 time blocks; each block's residual comes from ridge fitted on the other two, without the 24 hours before the block, whose targets fall inside it. Ridge's residuals on its own training rows were 8 to 33 % smaller on the inner splits, so trees fitted on them would correct too little. The final ridge is fitted on all training rows.
- **Settings:** learning rate 0.05, 15 leaves, depth 4, L2 penalty 10, 80 % of the inputs per tree, seeded and deterministic. 10 rounds and `min_data_in_leaf` 200 were chosen on the inner splits; more rounds made them worse. `lgbm_residual:v1:linear` fits a linear model in each leaf (`linear_tree`).
- **Ruled out.** Over all issue times both lose to `ridge:change:v2` in 2 (plain) and 3 (linear) of 4 folds. Flood size holds, false alarms are 4 (plain) and 3 (linear) against 3, and the high-water bias at +24 h shrinks from −3.8 to −3.2 cm. The trees mostly learned season, which 8 to 20 months of training can't support.

## Capped training (stress test)

`<model>:cap100` is the same model trained without any issue time whose cleaned level at the issue time or any target is above 100 cm (`models/capped.py`). Test rows are not filtered, so the four test floods above 100 cm lie beyond the levels and targets it learned from (lag and upstream inputs aren't capped). It shows how much flood size a model family loses on a flood bigger than its training range. It is a stress test only, never a live candidate: the variants sit in `STRESS_TESTS` in the registry and run only when named, e.g. `--models persistence,upstream:cap100`. Results: run [2026-10-15-capped-training](../analysis/model-evaluation/experiments.md#2026-10-15-capped-training).

## Known weaknesses of the current best

- **No gain at +1 h.** About 0.67 cm, persistence 0.66, `upstream` 0.60.
- **Too low at high water.** Bias about −1.5 to −1.7 cm at +6 h and −3.7 to −3.8 cm at +24 h. Rises are still caught late.
- **Misses 4 to 5 of 13 floods a day ahead.** 6 hours before the peak both see all 13, 12 hours before 11 to 12. The 165 cm flood of 2024-11-19 is seen only from 6 hours before (26 % of the rise at 24 h): ICON-D2 badly underforecast its rain.
- **Too high on small floods.** 12 hours before the 91 cm peak of 2026-02-22 they forecast 145 and 162 % of the rise.
- **False alarms:** 2 (`rain_change:v2:split`) and 3 (`ridge:change:v2`) in 18 test months; persistence none.
- **Chosen from many candidates** on inner splits that overlap earlier test periods.
- **Trained on day-old ICON-D2.** How the fitted coefficients behave on fresh runs shows only in live forecasts.

## Uncertainty bands

Every model forecast carries three bands, 80, 90 and 95 %: the observed level should lie inside in that share of cases. They come from the model's own past errors on the evaluation folds, never from the rows it was fitted on (`core/bands.py`, fitted by `pegel train-model` and stored in the model file). A model file trained before bands existed still loads; its forecasts just have none until the model is retrained.

**How.** Per lead k, an error scale grows with how much the model expects to change and with the forecast rain:

```
s_k = a_k + b_k · |forecast_k − last level| + c_k · ICON rain to hour k
```

with a, b, c ≥ 0 fitted by least squares on the absolute errors, and capped at the 99th percentile of the scales seen in calibration. The band is the forecast plus the 5 % and 95 % quantiles (for 90 %) of error / s_k. It is never narrower than ±1.5 cm, and its lower edge never goes below 0 cm.

**When an input is missing,** the model falls back to persistence (change exactly 0) and the band uses the quantiles of the persistence error instead. Missing ICON rain does the same even where the forecast still moves: never read as dry, the band only gets wider. If the bands fail for any other reason, the forecast is saved without them.

**Situation tag.** Each forecast gets a tag for the page. It names the situation; it doesn't pick the band. The first that matches:

| Tag | When | On the page |
|---|---|---|
| `degraded` | an input is missing, persistence bands | Eingeschränkte Vorhersage |
| `strong` | largest predicted change in 24 h ≥ 8 cm | Starke Änderung erwartet |
| `moving` | that change ≥ 2 cm, or ICON rain over 24 h ≥ 3 mm | Bewegung oder Regen erwartet |
| `calm` | otherwise | Ruhige Lage |

Thresholds and coverages are in `bands` in `config/pegel.json`.

**Why a scale and not one table per situation.** Three schemes were tried against one quantile table per lead, each calibrated only on the folds before its test fold: situation buckets from hydrology, buckets from a shallow tree, and the scale above. Only the scale beat the per-lead table in every fold and in 63 of 69 weeks (interval score at 90 %, leads 1 to 24: 11.8 against 18.2). The buckets left small cells whose tails varied threefold under bootstrap. Details in [learnings](../analysis/model-evaluation/learnings.md#2026-10-16--uncertainty-bands).

**Scored** in every evaluation run (`bands.csv`, a folded table in the run report): coverage, mean width and interval score per model, fold, situation, lead and coverage. Fold F1 has no earlier fold to calibrate on, so it is not scored.

**Limits.**
- On a rise into a flood the 95 % band holds only about 85 %: 14 % of those readings land above it. Don't call it "95 % sicher" on the page during a rise.
- A summer calibrated only on winters undercovered (F3: 83 % at 90 %). The live table includes one summer; watch coverage live.
- The upper edge can jump by up to 13 cm (p99) from one hour to the next at +6 h.
- Refit with every model: the scale depends on the model's predicted change.
