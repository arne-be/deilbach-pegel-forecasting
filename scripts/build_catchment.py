# /// script
# requires-python = ">=3.12"
# dependencies = ["pyshp==3.1.6", "pyproj==3.8.0", "shapely==2.2.0"]
# ///
"""Builds the catchment files in config/ from the NRW river map.

- catchment.geojson: the catchment above Kupferdreh, its zones and the forecast ring
- radolan_cells.json: the RADOLAN radar cells in each zone and in the whole catchment
- icon_d2_points.json: the ICON-D2 grid points to fetch for the rain forecast

Input is the sub-catchment layer of the NRW river map GSK3E (dl-de/zero-2-0):
https://www.opengeodata.nrw.de/produkte/umwelt_klima/wasser/oberflaechengewaesser/gsk3e/gsk3e_EPSG25832_Shape.zip
Unzip `Eingangsdaten/shapefile/gsk3e_basis_ezg.*` and pass the path without extension:

    uv run scripts/build_catchment.py <dir>/gsk3e_basis_ezg

Each sub-catchment names the one it drains into (GEBKZ3E_U), so the area above a gauge is the
sub-catchment holding the gauge plus everything that drains into it.
"""

import json
import sys
from pathlib import Path
from typing import Any

import shapefile
import shapely
from pyproj import Transformer
from shapely.geometry import Point, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

CONFIG = Path(__file__).resolve().parents[1] / "config"
DEILBACH_PREFIX = "2769"  # GSK3E codes of the Deilbach system
RING_BUFFER_M = 10_000
SIMPLIFY_M = 10

# RADOLAN RW grid: 900 x 900 cells of 1 km on DWD's polar stereographic projection.
# Corner and projection from DWD's RADOLAN/RADVOR format description.
RADOLAN_PROJ = "+proj=stere +lat_0=90 +lat_ts=60 +lon_0=10 +a=6370040 +b=6370040 +units=m"
RADOLAN_X0_M, RADOLAN_Y0_M = -523_462.2, -4_658_645.0  # south-west corner
RADOLAN_SIZE, RADOLAN_CELL_M = 900, 1000

# ICON-D2 regular lat-lon grid on DWD Open Data and Open-Meteo: 0.02 degree steps from here.
ICON_D2_LAT0, ICON_D2_LON0, ICON_D2_STEP = 43.18, -3.94, 0.02
# Every second grid point: 9 catchment points match all 36 within 3% (docs/catchment.md).
ICON_D2_EVERY = 2

# Gauge positions (lat, lon). Kupferdreh from its street address, the others from LANUV and BRW.
GAUGES = {
    "kupferdreh": (51.3868686, 7.0847720),
    "grenzweg": (51.3736283, 7.1335925),
    "langenberg": (51.3546158, 7.1218754),
    "nierenhof": (51.3658732, 7.1420589),
    "neviges": (51.3206716, 7.0838518),
}

to_utm = Transformer.from_crs(4326, 25832, always_xy=True).transform
to_wgs = Transformer.from_crs(25832, 4326, always_xy=True).transform


def load_units(path: str) -> dict[str, tuple[str, BaseGeometry]]:
    """Deilbach sub-catchments: code -> (downstream code, geometry in EPSG:25832)."""
    reader = shapefile.Reader(path)
    names = [field[0] for field in reader.fields[1:]]
    units = {}
    for shape_record in reader.iterShapeRecords():
        record = dict(zip(names, shape_record.record, strict=True))
        if record["GEBKZ3E"].startswith(DEILBACH_PREFIX):
            geometry = shape(shape_record.shape.__geo_interface__)
            units[record["GEBKZ3E"]] = (record["GEBKZ3E_U"], geometry)
    return units


def area_above(units: dict[str, tuple[str, BaseGeometry]], lat: float, lon: float) -> BaseGeometry:
    point = Point(to_utm(lon, lat))
    # A gauge on the river line can sit between two units; then take the nearest.
    start = min(units, key=lambda code: units[code][1].distance(point))
    children: dict[str, list[str]] = {}
    for code, (downstream, _) in units.items():
        children.setdefault(downstream, []).append(code)
    upstream, stack = set(), [start]
    while stack:
        code = stack.pop()
        upstream.add(code)
        stack.extend(children.get(code, []))
    # The buffer closes hairline gaps between neighbouring units.
    return unary_union([units[code][1] for code in upstream]).buffer(0.5).buffer(-0.5)


def feature(
    kind: str, feature_id: str, geometry: BaseGeometry, **properties: Any
) -> dict[str, Any]:
    simplified = shapely.transform(geometry.simplify(SIMPLIFY_M), to_wgs, interleaved=False)
    rounded = json.loads(
        json.dumps(mapping(simplified)), parse_float=lambda value: round(float(value), 5)
    )
    return {
        "type": "Feature",
        "properties": {
            "kind": kind,
            "id": feature_id,
            "area_km2": round(geometry.area / 1e6, 1),
            **properties,
        },
        "geometry": rounded,
    }


def radolan_cells(areas: dict[str, BaseGeometry]) -> dict[str, list[int]]:
    """Flat indices (row * 900 + col, row 0 in the south) of cells whose centre is in each area."""
    to_radolan = Transformer.from_crs(25832, RADOLAN_PROJ, always_xy=True).transform
    from_radolan = Transformer.from_crs(RADOLAN_PROJ, 25832, always_xy=True).transform
    min_x, min_y, max_x, max_y = shapely.transform(
        unary_union(list(areas.values())), to_radolan, interleaved=False
    ).bounds
    cells: dict[str, list[int]] = {name: [] for name in areas}
    for row in range(int((min_y - RADOLAN_Y0_M) // RADOLAN_CELL_M), RADOLAN_SIZE):
        y = RADOLAN_Y0_M + (row + 0.5) * RADOLAN_CELL_M
        if y > max_y + RADOLAN_CELL_M:
            break
        for col in range(int((min_x - RADOLAN_X0_M) // RADOLAN_CELL_M), RADOLAN_SIZE):
            x = RADOLAN_X0_M + (col + 0.5) * RADOLAN_CELL_M
            if x > max_x + RADOLAN_CELL_M:
                break
            centre = Point(from_radolan(x, y))
            for name, area in areas.items():
                if area.contains(centre):
                    cells[name].append(row * RADOLAN_SIZE + col)
    return cells


def icon_d2_points(catchment: BaseGeometry, ring: BaseGeometry) -> list[dict[str, Any]]:
    """Every second ICON-D2 grid point inside the ring, flagged when it lies in the catchment."""
    wgs_ring = shapely.transform(ring, to_wgs, interleaved=False)
    min_lon, min_lat, max_lon, max_lat = wgs_ring.bounds
    step = ICON_D2_STEP * ICON_D2_EVERY
    first_i = int((min_lat - ICON_D2_LAT0) // step)
    first_j = int((min_lon - ICON_D2_LON0) // step)
    points = []
    for i in range(first_i, int((max_lat - ICON_D2_LAT0) // step) + 2):
        for j in range(first_j, int((max_lon - ICON_D2_LON0) // step) + 2):
            lat = round(ICON_D2_LAT0 + i * step, 2)
            lon = round(ICON_D2_LON0 + j * step, 2)
            utm = Point(to_utm(lon, lat))
            if ring.contains(utm):
                points.append({"lat": lat, "lon": lon, "in_catchment": catchment.contains(utm)})
    return points


def write_json(name: str, content: object) -> None:
    (CONFIG / name).write_text(json.dumps(content, separators=(",", ":")) + "\n", encoding="utf-8")


def main(path: str) -> None:
    units = load_units(path)
    above = {gauge: area_above(units, *position) for gauge, position in GAUGES.items()}
    zones = {
        # zone id: (name, outlet gauge, geometry)
        "neviges": ("Hardenberger Bach above Neviges", "neviges", above["neviges"]),
        "upper_deilbach": (
            "Deilbach above Langenberg 2, without Neviges",
            "langenberg",
            above["langenberg"].difference(above["neviges"]),
        ),
        "felderbach": ("Felderbach above Nierenhof", "nierenhof", above["nierenhof"]),
        "middle": (
            "Between Langenberg 2 / Nierenhof and Grenzweg",
            "grenzweg",
            above["grenzweg"].difference(above["langenberg"]).difference(above["nierenhof"]),
        ),
        "lower": (
            "Below Grenzweg down to Kupferdreh",
            "kupferdreh",
            above["kupferdreh"].difference(above["grenzweg"]),
        ),
    }
    catchment = above["kupferdreh"]
    ring = catchment.buffer(RING_BUFFER_M)
    # Drop slivers left by the differences.
    cleaned = {
        zone_id: geometry.buffer(-1).buffer(1) for zone_id, (_, _, geometry) in zones.items()
    }
    features = [feature("catchment", "kupferdreh", catchment, name="Deilbach above Kupferdreh")]
    for zone_id, (name, outlet, _) in zones.items():
        features.append(feature("zone", zone_id, cleaned[zone_id], name=name, outlet_gauge=outlet))
    features.append(feature("forecast_ring", "ring_10km", ring, name="Catchment plus 10 km"))
    write_json("catchment.geojson", {"type": "FeatureCollection", "features": features})
    for item in features:
        properties = item["properties"]
        print(f"{properties['kind']:14} {properties['id']:15} {properties['area_km2']:7.1f} km²")

    cells = radolan_cells({**cleaned, "catchment": catchment})
    grid = {
        "product": "RW",
        "proj": RADOLAN_PROJ,
        "x0_m": RADOLAN_X0_M,
        "y0_m": RADOLAN_Y0_M,
        "cell_m": RADOLAN_CELL_M,
        "rows": RADOLAN_SIZE,
        "cols": RADOLAN_SIZE,
        "index": "row * cols + col, row 0 is the southernmost row",
    }
    write_json("radolan_cells.json", {"grid": grid, "cells": cells})
    print("radar cells:", {name: len(indices) for name, indices in cells.items()})

    points = icon_d2_points(catchment, ring)
    write_json(
        "icon_d2_points.json",
        {"model": "icon_d2", "grid_step_deg": ICON_D2_STEP * ICON_D2_EVERY, "points": points},
    )
    inside = sum(point["in_catchment"] for point in points)
    print(f"forecast points: {len(points)} in the ring, {inside} in the catchment")


if __name__ == "__main__":
    main(sys.argv[1])
