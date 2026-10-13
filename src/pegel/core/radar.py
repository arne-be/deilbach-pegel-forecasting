"""Radar rain series: zone means and the wettest catchment cell, from one hourly grid."""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta

from pegel.core.observations import require_utc
from pegel.core.series import Series, SeriesValue

# The area in the cells file that holds every catchment cell; all other areas are zones.
CATCHMENT_AREA = "catchment"


def radar_series(source: str, areas: Sequence[str]) -> dict[str, Series]:
    """The series each area of the cells file feeds, by area.

    Zones give `<source>:zone:<id>` (mean), the catchment `<source>:catchment:max`.
    """
    series = {}
    for area in areas:
        if area == CATCHMENT_AREA:
            name, location, aggregation = "catchment:max", "catchment", "max"
            description = "Wettest radar cell in the catchment, hourly, DWD RADOLAN RW"
        else:
            name, location, aggregation = f"zone:{area}", f"zone:{area}", "mean"
            description = f"Mean radar rain over zone {area}, hourly, DWD RADOLAN RW"
        series[area] = Series(
            id=f"{source}:{name}",
            variable="rain",
            unit="mm",
            source=source,
            location=location,
            kind="observation",
            aggregation=aggregation,
            period=timedelta(hours=1),
            description=description,
        )
    return series


def radar_values(
    series: Mapping[str, Series],
    cells: Mapping[str, Sequence[int]],
    valid_at: datetime,
    rain_at: Callable[[int], float | None],
    available_at: datetime,
) -> list[SeriesValue]:
    """Each area's mean (zones) or max (catchment) over its cells with data, with the coverage.

    `rain_at` gives a cell's rain in mm or None without data. A series without any cell with data
    is left out, so the caller can see and log it.
    """
    require_utc(valid_at, "valid_at")
    values = []
    for area, indices in cells.items():
        rains = [rain for rain in map(rain_at, indices) if rain is not None]
        if not rains:
            continue
        one = series[area]
        value = max(rains) if one.aggregation == "max" else sum(rains) / len(rains)
        coverage = len(rains) / len(indices)
        values.append(SeriesValue(one.id, valid_at, value, available_at, coverage))
    return values
