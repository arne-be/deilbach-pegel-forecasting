from datetime import UTC, datetime

import pytest

from pegel.adapters.sources.lanuv import parse_lanuv_value


def test_reading_is_kept_in_centimetres_and_utc() -> None:
    observation = parse_lanuv_value("langenberg", "2026-10-13T09:05:00.000+01:00", 33.4)
    assert observation is not None
    assert observation.observed_at == datetime(2026, 10, 13, 8, 5, tzinfo=UTC)
    assert observation.level_cm == 33.4


def test_csv_text_value_and_negative_level_are_kept() -> None:
    observation = parse_lanuv_value("nierenhof", "2020-01-01T00:00:00+01:00", "-3.5")
    assert observation is not None
    assert observation.level_cm == -3.5


@pytest.mark.parametrize("value", [None, "NA", ""])
def test_gaps_are_skipped(value: str | None) -> None:
    assert parse_lanuv_value("neviges", "2020-01-01T00:00:00+01:00", value) is None


def test_timestamp_without_offset_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_lanuv_value("neviges", "2020-01-01T00:00:00", 10)
