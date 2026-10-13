import json
from typing import Any

import pytest

from pegel.config import DEFAULT_CONFIG_PATH

CATCHMENT_PATH = DEFAULT_CONFIG_PATH.parent / "catchment.geojson"


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
