# Outlier removal for the Kupferdreh level

Exploration, not production code. It compares three **live** outlier filters for
the raw Kupferdreh level. Each one decides as soon as a new reading arrives,
using only that reading and the ones before it, which is all the hourly job
has. They use nothing but the level series itself (no rain, no upstream
gauges).

Data: all 30,746 hourly readings in `raw_observations` (prod), 2023-03-06 to
2026-10-13.

## What the outliers look like

- **2.98 m is an error value.** It shows up 97 times, all in 2023, mostly for
  1–2 hours, but also in runs of 4, 6 and 13 hours. The highest real level in the
  data is 1.23 m (19 Nov 2024).
- **Fake values in between**, often next to a 2.98: 1.50, 1.55, 2.11, 2.72 m,
  sometimes for several hours.
- **Small one-hour spikes** since September 2026. The level sits near its floor
  at −0.26 m and jumps to +0.15…+0.55 m for one reading, then comes back.
- **Real behaviour:** the level rises by up to ~0.35 m/h (one summer storm went
  from 0.07 to 0.45 m in an hour). It falls slowly, never faster than 0.18 m/h
  once spikes are removed.

## The three live filters

Code: [`methods.py`](methods.py). Each filter keeps a small state built only
from readings it accepted, so an outlier can't drag the reference along.

1. **Step Hampel.** The Hampel test applied to the rate of change. It looks at
   the median and MAD of the last 6 accepted hourly steps. A reading is an
   outlier if its step from the last accepted reading is far from that median
   (4 × MAD, at least 0.35 m/h). A steady rise counts as normal, a sudden jump
   doesn't.
2. **Rate envelope.** Physical limits: from the last accepted reading the level
   may rise at most 0.4 m/h and fall at most 0.25 m/h.
3. **Kalman filter.** It tracks the level and its trend and predicts the next
   reading. A reading is an outlier if it is more than 4 σ (at least 0.15 m)
   from the prediction. On a rising limb the prediction rises too, so real
   floods pass.

Three rules are shared, because without them every live filter breaks on this
data:

- **The allowed change grows with the time since the last accepted reading,
  but only up to 3 hours.** Without the cap, a sensor stuck at 2.98 m would
  become "plausible" after a few hours and be accepted.
- **Back to a recent level is always plausible.** A small spike can pass a live
  check, e.g. −0.24 → 0.08 m, which looks exactly like the start of a real
  rise. The true level after it then looks like an impossible fall. So a
  reading that fails the check is still accepted if the level was there within
  the last 12 hours, and the readings in between are forgotten. Without this
  rule, the filters rejected the true level for up to 9 hours after a spike.
- **After 16 hours without an accepted reading, a filter starts over** from
  the new reading, so a real change during a data gap can't lock it out. The
  longest stuck run seen is 13 hours.

## Results

The offline Excursion filter from the first comparison is shown as a
reference. It needs to see the spike come back, so it can't run live.

| | Step Hampel | Rate envelope | Kalman | *Excursion (offline)* |
|:--|--:|--:|--:|--:|
| points removed | 141 (0.46 %) | 139 (0.45 %) | 145 (0.47 %) | *142* |
| 2.98 m values caught | 97 / 97 | 97 / 97 | 97 / 97 | *97 / 97* |
| removed during real events¹ | 0 | 0 | 0 | *0* |
| jumps > 0.3 m left in kept data | 7 | 11 | **4** | *4* |
| highest kept value | 1.23 m | 1.23 m | 1.23 m | *1.23 m* |

¹ Up to a day before or two days after 8 events checked by eye: the largest
floods (Dec 2023, Jan 2024, Nov 2024) and the fastest real rises (Jun 2023,
Aug 2024, Sep 2025, May/Jun 2026).

How many points two filters both flag (the diagonal is the total):

| | Step Hampel | Rate envelope | Kalman |
|:--|--:|--:|--:|
| Step Hampel | 141 | 139 | 141 |
| Rate envelope | 139 | 139 | 139 |
| Kalman | 141 | 139 | 145 |

They mostly agree. Compared with the offline reference:
- **Step Hampel** misses 2 small spikes (e.g. 2026-06-29 −0.24 → 0.08 m) and
  removes 1 extra point, in the noisy 2023-07-09 storm.
- **Rate envelope** misses 4 small spikes: a spike under 0.4 m passes, and so
  does the second reading of a two-hour spike (2026-10-02, 0.51 then 0.52 m).
- **Kalman** misses 1 small spike. It removes 4 extra points: three in the
  zig-zag storms of July 2023, which bounce by ±0.2–0.4 m per hour and fall
  faster than the river can, and one 10 cm dip on 2024-09-04 that might be
  real.

The spikes that get through are inherent to live filtering. When a 0.3 m jump
arrives, it looks the same as the start of a real rise.

## Checks that they really work live

`outliers.py` runs these every time:

- **Causality:** each filter runs on the series cut at 7 points and must give
  exactly the same flags as on the full series. Later data never changes an
  earlier decision.
- **No stored state needed:** each month is replayed with a fresh filter that
  only gets the 48 hours before it. That gives 0 differences for all three
  filters, so the hourly job can rebuild the state from the last 48 hours of
  raw readings each run.
- **Synthetic cases:** spikes, back-to-back spikes, a two-hour plateau and a
  fast real rise, plus a small spike that passes. The true level after that
  spike must not be rejected; this check fails without the
  "back to a recent level" rule.

## Plots

Grey is raw, blue is kept, red dots are removed.

**Whole series.**
![Whole series](plots/full.png)

**Spike period, summer 2023.**
![Summer 2023](plots/spikes-2023-08.png)

**13 hours stuck at 2.98 m.** All three reject the whole run and accept the
true level straight after.
![13 h stuck](plots/stuck-2023-09.png)

**Recent small spikes (Sept/Oct 2026).** Rate envelope lets the two-hour spike
on 2 Oct and the 0.15 m spike on 3 Oct through. The others catch everything
except one second reading on 26 Sept.
![2026 spikes](plots/spikes-2026-09.png)

**Fastest real rise, June 2023.** Nothing removed.
![Storm Jun 2023](plots/storm-2023-06.png)

**Highest real flood, Nov 2024.** Nothing removed.
![Flood Nov 2024](plots/flood-2024-11.png)

More plots: [6 hours stuck, then a fake drop](plots/stuck-2023-12.png),
[long wet period, winter 2023/24](plots/flood-2023-12.png),
[3-hour spike at 2.7 m, Feb 2025](plots/spike-2025-02.png),
[distribution of hourly changes](plots/diffs.png).

## Parameter choices

Results of the sweeps (removed / removed during real events / jumps left):

- **Rate envelope**, rise limit: 0.3 m/h → 145 / 2 / 4, 0.4 m/h → 139 / 0 / 11,
  0.5 m/h → 133 / 0 / 22. The fall limit (0.2–0.3 m/h) barely matters, because
  the "back to a recent level" rule handles the drops.
- **Step Hampel**, minimum rate: 0.25 → 144 / 1 / 4, 0.35 → 141 / 0 / 7,
  0.45 → 133 / 0 / 22. The MAD factor (3–5) makes no difference: at normal
  levels the steps are so steady that the minimum always wins.
- **Kalman**, gate × trend noise: 4 σ with 0.005 → 145 / 0 / 4 (chosen);
  3 σ → loses 1–3 real points; 5 σ or noisier trends → 13–44 jumps left.

## Recommendation

**Kalman filter.** It is the only live filter that matches the offline
reference: all 2.98 m values caught, nothing lost in real floods, and only 4
jumps left. Because it follows the trend, it doesn't need a fixed rise limit,
which keeps it from being too strict or too loose during fast real rises.

**Rate envelope** is the simple fallback: a two-line check, easy to explain,
with physical limits anyone can check. The price is a few more small spikes
getting through.

For the hourly job: load the last 48 hours of raw readings, run the filter
from the start of that window and use its decision for the newest reading.
Raw data stays as received; the decision goes into the cleaned series.

## How to rerun

Export the data (read only, prod connection string only in the environment for
that one command), then run the comparison. pandas and matplotlib are only
pulled in for this run; they are not project dependencies.

```
cd analysis/outliers
DATABASE_URL="$(neon cs prod --project-id <project-id> --role-name pegel_owner --database-name pegel </dev/null)" \
  uv run -q --no-project --with 'psycopg[binary]==3.3.6' python export.py data/kupferdreh.csv
uv run -q --no-project --with pandas --with matplotlib --with tabulate python outliers.py data/kupferdreh.csv
```

`data/` is gitignored, because the raw client data stays out of the repo.
