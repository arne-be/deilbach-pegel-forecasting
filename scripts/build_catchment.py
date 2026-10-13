# /// script
# requires-python = ">=3.12"
# dependencies = ["pyshp==3.1.6", "pyproj==3.8.0", "shapely==2.2.0"]
# ///
"""Builds config/catchment.geojson: the catchment above Kupferdreh, its zones and the forecast ring.

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

OUTPUT = Path(__file__).resolve().parents[1] / "config" / "catchment.geojson"
DEILBACH_PREFIX = "2769"  # GSK3E codes of the Deilbach system
RING_BUFFER_M = 10_000
SIMPLIFY_M = 10

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
    features = [feature("catchment", "kupferdreh", catchment, name="Deilbach above Kupferdreh")]
    for zone_id, (name, outlet, geometry) in zones.items():
        cleaned = geometry.buffer(-1).buffer(1)  # drop slivers left by the differences
        features.append(feature("zone", zone_id, cleaned, name=name, outlet_gauge=outlet))
    features.append(
        feature(
            "forecast_ring",
            "ring_10km",
            catchment.buffer(RING_BUFFER_M),
            name="Catchment plus 10 km",
        )
    )
    collection = {"type": "FeatureCollection", "features": features}
    OUTPUT.write_text(json.dumps(collection, separators=(",", ":")) + "\n", encoding="utf-8")
    for item in features:
        properties = item["properties"]
        print(f"{properties['kind']:14} {properties['id']:15} {properties['area_km2']:7.1f} km²")


if __name__ == "__main__":
    main(sys.argv[1])
