import json
from typing import Any

import pytest

from pegel.config import config_file, load_config

CATCHMENT_PATH = config_file("catchment.geojson")


def _features() -> dict[tuple[str, str], dict[str, Any]]:
    collection = json.loads(CATCHMENT_PATH.read_text(encoding="utf-8"))
    return {(f["properties"]["kind"], f["properties"]["id"]): f for f in collection["features"]}


def test_catchment_has_the_five_zones_and_the_ring() -> None:
    assert set(_features()) == {
        ("catchment", "kupferdreh"),
        ("zone", "neviges"),
        ("zone", "upper_deilbach"),
        ("zone", "felderbach"),
        ("zone", "middle"),
        ("zone", "lower"),
        ("forecast_ring", "ring_10km"),
    }


def test_zones_add_up_to_the_catchment() -> None:
    features = _features()
    zones = [feature for (kind, _), feature in features.items() if kind == "zone"]
    zone_area = sum(zone["properties"]["area_km2"] for zone in zones)
    catchment_area = features[("catchment", "kupferdreh")]["properties"]["area_km2"]
    assert zone_area == pytest.approx(catchment_area, abs=0.5)


def test_radar_cells_cover_every_zone_and_the_catchment() -> None:
    cells_file = config_file(load_config().rain.radar.cells_file)
    cells = json.loads(cells_file.read_text(encoding="utf-8"))["cells"]
    zones = {zone_id for kind, zone_id in _features() if kind == "zone"}
    assert set(cells) == zones | {"catchment"}
    assert sum(len(cells[zone]) for zone in zones) == len(cells["catchment"])


def test_forecast_points_include_catchment_points() -> None:
    points_file = config_file(load_config().rain.forecast.points_file)
    points = json.loads(points_file.read_text(encoding="utf-8"))["points"]
    assert sum(point["in_catchment"] for point in points) == 9
    assert len(points) == 70
