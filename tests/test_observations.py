from datetime import UTC, datetime, timedelta, timezone

import pytest

from pegel.core.observations import Observation


def test_negative_level_is_kept() -> None:
    observation = Observation("kupferdreh", datetime(2026, 10, 12, 12, 22, tzinfo=UTC), -0.25)
    assert observation.level_m == -0.25


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="UTC"):
        Observation("kupferdreh", datetime(2026, 10, 12, 12, 22), 0.1)  # noqa: DTZ001


def test_non_utc_timestamp_is_rejected() -> None:
    berlin_summer = timezone(timedelta(hours=2))
    with pytest.raises(ValueError, match="UTC"):
        Observation("kupferdreh", datetime(2026, 10, 12, 14, 22, tzinfo=berlin_summer), 0.1)
