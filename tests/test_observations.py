from datetime import UTC, datetime, timedelta, timezone

import pytest

from pegel.core.observations import Observation


def test_negative_level_is_kept() -> None:
    observation = Observation("kupferdreh", datetime(2026, 10, 12, 12, 22, tzinfo=UTC), -25.0)
    assert observation.level_cm == -25.0


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="UTC"):
        Observation("kupferdreh", datetime(2026, 10, 12, 12, 22), 10.0)  # noqa: DTZ001


def test_non_utc_timestamp_is_rejected() -> None:
    berlin_summer = timezone(timedelta(hours=2))
    with pytest.raises(ValueError, match="UTC"):
        Observation("kupferdreh", datetime(2026, 10, 12, 14, 22, tzinfo=berlin_summer), 10.0)
