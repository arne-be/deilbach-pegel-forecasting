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

For training before we started collecting, Open-Meteo's Previous Runs API has ICON-D2 from February 2024. It gives, for each hour, the forecast from the newest run and from the run about a day earlier, not every lead time. These rows are stored under their own source, `open_meteo_previous_runs`, with an approximate run time.

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
