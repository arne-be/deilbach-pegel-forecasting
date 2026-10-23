# Catchment and rain inputs

Where the water at the Kupferdreh gauge comes from, how we split that area, and which rain data the forecast will use. The outlines live in [`config/catchment.geojson`](../config/catchment.geojson).

![Deilbach catchment above Kupferdreh with five zones, gauges and the forecast ring](images/catchment-map.jpg)

Base map © OpenStreetMap contributors. Catchment and rivers from the NRW river map GSK3E.

## Catchment

The catchment above Kupferdreh covers 111.5 km². All rain that falls inside it flows past the gauge. It's built from the sub-catchments of the NRW river map GSK3E. Each sub-catchment names the one it drains into, so the area above a gauge is the sub-catchment holding the gauge plus everything upstream of it.

The result matches the areas the gauge operators publish:

| Gauge | Built | Published |
|---|---|---|
| Langenberg 2 | 58.2 km² | 57.74 km² |
| Grenzweg | 93.3 km² | 93.55 km² |
| Nierenhof | 22.5 km² | 22.00 km² |
| Neviges | 20.3 km² | 20.20 km² |

The last sub-catchment runs to the Deilbach mouth at the Ruhr, a little past the Kupferdreh gauge. So the true area above Kupferdreh is slightly under 111.5 km².

## Zones

The catchment is split at the gauges into five zones. Rain on a zone passes the gauge at its outlet before it reaches Kupferdreh. Zones without a usable gauge give no such early signal, so for them rain data is the only warning.

| Zone id | Area | Outlet gauge | Radar cells |
|---|---|---|---|
| `neviges` | 20.3 km² | Neviges | 21 |
| `upper_deilbach` | 37.9 km² | Langenberg 2 | 41 |
| `felderbach` | 22.5 km² | Nierenhof | 25 |
| `middle` | 12.5 km² | Grenzweg (BRW, not used yet) | 14 |
| `lower` | 18.2 km² | Kupferdreh | 18 |

`middle` only drains through Grenzweg. Until BRW allows us to use that gauge, `middle` behaves like `lower`: no gauge sees its water before Kupferdreh.

Radar cells are the 1 km RADOLAN cells whose centre lies in the zone.

## Forecast ring

`ring_10km` is the catchment widened by 10 km (872 km², 281 ICON-D2 points, 70 of them used). Weather models often place a shower 10 to 30 km from where it falls. The ring catches storms the model puts just outside the catchment.

## Rain data we collect

Two kinds: observed rain (what has fallen) and rain forecasts (what will fall). Both are stored as rain in mm per hour, with the end of the hour as the time.

### Observed rain: DWD RADOLAN RW

The hourly radar rain map, corrected with rain gauges, 1 km cells. The hourly product covers the hour ending at :50 UTC and is out about 25 minutes later. History goes back to 2005.

Six values per hour:

| Series | Value |
|---|---|
| `zone:neviges` … `zone:lower` | Mean of the radar cells in each zone (5 values) |
| `catchment:max` | Wettest single cell in the catchment |

The mean over the whole catchment is the area-weighted mean of the zones, so it isn't stored separately.

The series ids start with the source, e.g. `radolan_rw:zone:neviges`, and each value is stored at the product time (the end of its hour). The hourly run reads the newest files of DWD's recent archive (the live folder switched to HDF5 on 2026-10-20). History comes from DWD's archives: monthly tars up to 2024, single files from 2025 on.

**For training:** the hourly RW file for product time hh:50 shows up in the live folder about 26 minutes later (48 products on 2026-10-11 to 13, from the folder listing: 25.8 to 26.5 min for the bz2 files, 30.2 min worst over all 10-minute products). The recent archive, which the hourly run reads since 2026-10-23, takes 26.8 to 31.6 min (346 hourly products, 2026-10-09 to 23). Training uses a value only if its `available_at` ≤ the issue time. The hourly step stamps values with the issue slot (:30) of the run that fetched them; the exact fetch time stays in `ingested_at`. Backfilled hours get what the live system would have done: the first hourly run (:30) at or after valid_at + `available_after`, which is `rain.radar.available_after_minutes` (35). So an hh:50 product counts from the :30 run of the next hour; any delay up to 40 minutes gives the same run.

Cells flagged as no data, clutter or negative are left out, and the coverage says what share of a series' cells had data. Cells filled from interpolated rain gauges (where the radar sees nothing) count as data. The bits are in DWD's [format description](https://opendata.dwd.de/climate_environment/CDC/help/RADOLAN/Unterstuetzungsdokumente/RADOLAN-RADVOR-Kompositformat_2.6.pdf), chapter 1.2. The parser rejects composites on the WGS84 grid (header `VS 5`), because the cells are built on DWD's sphere grid; RW still uses it.

The grid was checked three ways: DWD's corner table matches our projection within 4 m, wradlib reads the same values in the same cell order (row 0 in the south), and on 2024-11-19 the radar's blind spot sits exactly at the Essen radar site, next to DWD station 01303. Around that station the radar gave 2.4 and 30.8 mm on 18 and 19 November 2024; the rain gauge measured 2.8 and 31.0 mm.

### Rain forecast: ICON-D2 via Open-Meteo

DWD's 2.2 km weather model. A new run starts every 3 hours and reaches 48 hours ahead. Open-Meteo serves it as JSON (`models=icon_d2`, `hourly=precipitation`) and keeps past forecasts. The free tier is for non-commercial use only, which fits this project as long as it stays non-commercial.

We fetch every second ICON-D2 grid point (0.04°, about 4.4 km apart): 70 points in the ring, 9 of them in the catchment. We fetch once per new run, so about 8 times a day, and store the run's start time with each forecast. Training then only sees forecasts as they were issued.

Per run, for each lead time from +1 h to +48 h:

| Series | Value | Points |
|---|---|---|
| `catchment:mean` | Mean over the catchment | 9 |
| `ring:p90` | 90th percentile over the ring | 70 |

That's 2 × 48 = 96 values per run, about 70 Open-Meteo calls per run and 560 a day. The free tier allows 10,000 a day.

Why every second point: on three rainy days in 2024 and 2026, the mean of 9 points matched the mean of all 36 catchment points within 3% of the 48-hour total. One centre point was off by up to 25%, three points by up to 22%. The ring value is rougher with 70 points (one peak came out at 3.1 instead of 4.6 mm/h). It only has to say whether a storm is near.

Forecasts per zone are left out for now. Single zones would get only 1 to 3 points. Open-Meteo keeps its archive, so we can fetch all points later and test whether zones help.

Series ids carry the source: `open_meteo_icon_d2:catchment:mean` and `open_meteo_icon_d2:ring:p90`. The code is `src/pegel/core/rain_forecast.py`, `src/pegel/adapters/sources/open_meteo.py` and `src/pegel/jobs/rain_forecast.py`.

#### Which run a forecast comes from

Open-Meteo's model metadata says which run is the newest: `https://api.open-meteo.com/data/dwd_icon_d2/static/meta.json` has `last_run_initialisation_time` (the run's start, Unix seconds) and `last_run_availability_time` (when Open-Meteo started serving it). Runs start at 00, 03, … 21 UTC and come out about 85 minutes later (run 09:00 was served from 10:25).

The hourly step reads the metadata first. It then wants every run of the last 24 hours, up to the newest, that the live catchment series doesn't have yet. If there is none, it stops: no forecast request. Otherwise it fetches them newest first, at most 4 per hour: the level forecast needs the newest run, older ones only matter for training, so after a long outage the next hours fetch the rest. A run only 24 hours late still covers half the horizon; older ones are left to the archive.

Each run comes from Open-Meteo's Single Runs API (`single-runs-api.open-meteo.com/v1/forecast`), which takes the forecast parameters plus `run=2026-10-13T09:00`. The live forecast API only serves the newest run, so a missed run was lost before. Single Runs keeps runs from about May 2026 on and answers HTTP 400 for older ones. It doesn't take `start_hour`, so we ask for `forecast_hours=50`: the hours from the run start to run + 49 h. For run 09:00 on 2026-10-13 it gave the same values as the live API. It served the 18:00 run before the metadata named it, so going by the metadata never asks too early.

Each run is checked before it's stored: the hours run from run + 1 h without a gap, and each point has data from run + 1 h to exactly run + 48 h and none after. A shortened answer, or one from another run, ends early or late, and nothing of that run is stored.

Only run < valid_at ≤ run + 48 h is stored. `precipitation` is the sum of the preceding hour (Open-Meteo docs), so the time Open-Meteo gives is already `valid_at`. Each run is available from the issue slot of its fetch: a run caught up late is stored as late.

The request uses `cell_selection=nearest`. Without it Open-Meteo may pick a neighbouring cell with a better-matching elevation; one of our 70 points came back 0.02° off.

Each request (metadata and runs) gets two tries of at most 60 seconds, 5 seconds apart, on a timeout, network error or 5xx. From Lambda, single requests have timed out and got HTTP 503; the first request for a new run once took longer than 15 seconds. HTTP 429 isn't retried. A failing run stops the catch-up for this hour and keeps the runs stored before it; the next hour tries the missing runs again. After 2 minutes the step starts no older run, since a slow Open-Meteo can take about 2 minutes per run and the level forecast must still fit in the Lambda's 15 minutes.

#### Archive: Previous Runs API

For training before we started collecting, Open-Meteo's Previous Runs API (`previous-runs-api.open-meteo.com`) has ICON-D2 with both variables from late January 2024; we load from 2024-02-01. It doesn't keep every lead time, only two per hour:

| Variable | Comes from | Lead time |
|---|---|---|
| `precipitation` (day 0) | newest run that started before valid_at | 1 to 3 h |
| `precipitation_previous_day1` | newest run that started before valid_at − 24 h | 25 to 27 h |

`previous_day2` is empty, since ICON-D2 reaches only 48 hours.

We checked this against Open-Meteo's Single Runs API, which serves whole runs by start time but only from April 2026. On a rainy day (2026-10-01) nearly every rainy hour matched the run the rule predicts. Two of the day-1 values matched no run, so the run time is a close approximation, not exact. The rule is assumed to hold for 2024 too.

These rows go under their own source, `open_meteo_previous_runs`, with run_at set by that rule (`archive_run_at`). Both variables go into the same two series. Their lead times differ, so they never share a key. Hours where any point is missing are skipped. The last 3 hours before the fetch are left out, because their day-0 values may still come from a longer lead time.

**For training:** a run is only out about 85 minutes after run_at (measured 84.8 and 85.8 min for the 09 and 12 UTC runs on 2026-10-13, as `last_run_availability_time − last_run_initialisation_time`). Training uses a value only if its `available_at` ≤ the issue time. The live step stamps a run with the issue slot (:30) of the run that fetched it; the exact fetch time stays in `fetched_at`. Archive rows get what the live system would have done: the first hourly run (:30) at or after run_at + `available_after`, which is `rain.forecast.available_after_minutes` (120) for both sources. Any delay between 91 and 150 minutes gives the same :30 run, so 120 keeps a wide margin at no cost. Most day-0 values (lead 1 to 3 h) weren't available until after their hour had started, so treat them as close to an observation, not a forecast.

#### What a model sees at an issue time

The figures use one real issue time, 19 Nov 2024 at 12:30 UTC, a flood day.

**Live, we keep whole runs.** At 12:30 the 12:00 run isn't ready yet, so we use the 09:00 run. The forecast for 1 hour ahead is then a 4-hour forecast; the one for 24 hours ahead a 27-hour forecast.

![ICON-D2 runs at 03, 06, 09 and 12 UTC; the 09:00 run is the newest one ready at 12:30](images/icon-d2-live-runs.svg)

**In the archive only the day-old values are known.** At 12:30 the fresh values for the coming hours come from runs that aren't ready yet. The first one or two hours sometimes get a fresh value.

![For each hour, the fresh value is not yet known at 12:30; the day-old value is known up to 12:00 the next day](images/icon-d2-archive-values.svg)

So live, short hours get short, sharp forecasts; in the archive every hour gets a 25–27 hour forecast. The two only meet around 22–24 hours ahead.

![Live forecast lead rises from 4 to 27 hours; the archive lead stays between 25 and 27 hours](images/icon-d2-forecast-lead.svg)

- **Coverage is fine.** The archive always has a known value up to 22½ to 24½ hours ahead, so the 24 hourly sums of the evaluation dataset are complete.
- **The backtest is fair between models**, since all get the same day-old forecasts.
- **Live will differ.** A model trained on day-old forecasts learned to trust them little, so live it may underuse good short-range rain.

Backfill:

```
uv run pegel backfill-forecast --from 2024-02-01 [--to 2026-10-13]
```

It asks for 14 days of all 70 points per request (70 calls by Open-Meteo's count) and waits a minute between requests, so it stays well under 600 calls a minute and 5,000 an hour. From 2024-02-01 to October 2026 that's 71 requests, about 5,000 calls and 71 minutes. It stops before 9,000 calls in one invocation and prints the date to resume from. Reruns change nothing.

### Later

| Data | Why it waits |
|---|---|
| LANUV rain gauges Velbert-Neviges and Velbert-Langenberg Sender (hourly) | Only the last 7 days exist. Useful to check the radar, not for training. |
| DWD rain gauge Essen-Bredeney 01303 (10 min, since 1994) | 8 km outside the catchment. Useful to check the radar history. |
| DWD AMBAV soil moisture at 01303 (daily) | Rain sums over the last days carry much of the same signal. |
| ICON-D2-EPS rain probabilities | Not checked yet whether Open-Meteo serves and archives it. |

## Rebuilding the outlines

`scripts/build_catchment.py` writes three files to `config/`: `catchment.geojson` (outlines), `radolan_cells.json` (radar cells per zone) and `icon_d2_points.json` (forecast points). It needs the GSK3E shapefile (430 MB), which isn't in the repo:

```
curl -O https://www.opengeodata.nrw.de/produkte/umwelt_klima/wasser/oberflaechengewaesser/gsk3e/gsk3e_EPSG25832_Shape.zip
unzip -j gsk3e_EPSG25832_Shape.zip 'Eingangsdaten/shapefile/gsk3e_basis_ezg.*' -d gsk3e
uv run scripts/build_catchment.py gsk3e/gsk3e_basis_ezg
```

The script declares its own dependencies, so `uv run` installs them in a temporary environment without touching the project's.

## Sources and licences

| Data | Source | Licence |
|---|---|---|
| Catchments and rivers | GSK3E, LANUV NRW (edition 2019) | dl-de/zero-2-0 |
| Radar rain, soil moisture | DWD Open Data | CC BY 4.0, credit "Datenbasis: Deutscher Wetterdienst" |
| ICON-D2 forecasts | DWD via Open-Meteo | CC BY 4.0, non-commercial free tier |
| Base map in the image | OpenStreetMap | ODbL |
