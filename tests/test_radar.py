from datetime import UTC, datetime, timedelta

import pytest

from pegel.core.radar import radar_series, radar_values
from pegel.core.series import SeriesValue

VALID_AT = datetime(2024, 11, 19, 8, 50, tzinfo=UTC)
RAIN = {1: 1.0, 2: 2.0, 3: None, 4: 4.0, 5: None, 6: None}
AVAILABLE_AT = datetime(2024, 11, 19, 9, 30, tzinfo=UTC)
SERIES = radar_series("radolan_rw", ["upper", "lower", "dry", "catchment"])


def test_series_ids_and_metadata() -> None:
    assert [one.id for one in SERIES.values()] == [
        "radolan_rw:zone:upper",
        "radolan_rw:zone:lower",
        "radolan_rw:zone:dry",
        "radolan_rw:catchment:max",
    ]
    catchment = SERIES["catchment"]
    assert (catchment.location, catchment.aggregation, catchment.unit) == ("catchment", "max", "mm")
    assert (SERIES["upper"].aggregation, SERIES["upper"].kind) == ("mean", "observation")
    assert SERIES["upper"].period == timedelta(hours=1)


def test_zones_get_the_mean_of_cells_with_data_and_their_share() -> None:
    values = radar_values(
        SERIES, {"upper": [1, 2, 3], "lower": [4]}, VALID_AT, RAIN.get, AVAILABLE_AT
    )
    assert values == [
        SeriesValue("radolan_rw:zone:upper", VALID_AT, 1.5, AVAILABLE_AT, 2 / 3),
        SeriesValue("radolan_rw:zone:lower", VALID_AT, 4.0, AVAILABLE_AT, 1.0),
    ]


def test_catchment_gets_the_wettest_cell() -> None:
    values = radar_values(SERIES, {"catchment": [1, 2, 3, 4]}, VALID_AT, RAIN.get, AVAILABLE_AT)
    assert values == [SeriesValue("radolan_rw:catchment:max", VALID_AT, 4.0, AVAILABLE_AT, 0.75)]


def test_series_without_data_is_left_out() -> None:
    cells = {"upper": [1], "dry": [5, 6], "catchment": [5]}
    values = radar_values(SERIES, cells, VALID_AT, RAIN.get, AVAILABLE_AT)
    assert [value.series_id for value in values] == ["radolan_rw:zone:upper"]


def test_valid_at_must_be_utc() -> None:
    naive = datetime(2024, 11, 19, 8, 50)  # noqa: DTZ001
    with pytest.raises(ValueError):
        radar_values(SERIES, {"upper": [1]}, naive, RAIN.get, AVAILABLE_AT)
