from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg.rows import TupleRow

from pegel.adapters.storage.forecasts import newest_forecast
from pegel.adapters.storage.observations import fetch_observations
from pegel.config import Station, load_config
from pegel.core.observations import Observation
from pegel.jobs.pipeline import (
    NoObservationError,
    backfill,
    fetch_by_source,
    forecast,
    run_hourly,
)

Conn = psycopg.Connection[TupleRow]
CONFIG = load_config()
STATION = CONFIG.station(CONFIG.forecast.station_id)
ISSUED_AT = datetime(2026, 10, 12, 13, 30, tzinfo=UTC)
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


class FakeSource:
    """Serves hourly readings at :22 and records the windows it was asked for."""

    def __init__(self, readings: dict[datetime, float]) -> None:
        self.readings = readings
        self.windows: list[tuple[datetime, datetime]] = []

    def __call__(self, station: Station, start: datetime, end: datetime) -> list[Observation]:
        self.windows.append((start, end))
        return [
            Observation(station.id, observed_at, level)
            for observed_at, level in sorted(self.readings.items())
            if start <= observed_at < end
        ]


def readings_before(issued_at: datetime, levels: list[float]) -> dict[datetime, float]:
    newest = issued_at.replace(minute=22)
    return {newest - timedelta(hours=len(levels) - 1 - i): lvl for i, lvl in enumerate(levels)}


def test_hourly_run_forecasts_the_newest_level(conn: Conn) -> None:
    source = FakeSource(readings_before(ISSUED_AT, [10.0, 20.0, -21.0]))
    result = run_hourly(source, conn, CONFIG, ISSUED_AT)
    assert {point.level_cm for point in result.points} == {-21.0}


def test_hourly_run_stores_the_forecast(conn: Conn) -> None:
    source = FakeSource(readings_before(ISSUED_AT, [10.0]))
    result = run_hourly(source, conn, CONFIG, ISSUED_AT)
    assert newest_forecast(conn, STATION.id, result.model) == result


def test_hourly_run_ignores_readings_after_issue_time(conn: Conn) -> None:
    readings = readings_before(ISSUED_AT, [0.1]) | {ISSUED_AT + timedelta(minutes=52): 0.9}
    result = run_hourly(FakeSource(readings), conn, CONFIG, ISSUED_AT)
    assert result.newest_observation_at == ISSUED_AT.replace(minute=22)


def test_hourly_run_fetches_the_lookback_window(conn: Conn) -> None:
    source = FakeSource(readings_before(ISSUED_AT, [10.0]))
    run_hourly(source, conn, CONFIG, ISSUED_AT)
    lookback = timedelta(hours=CONFIG.forecast.ingest_lookback_hours)
    assert source.windows[0] == (ISSUED_AT - lookback, ISSUED_AT)


def test_hourly_run_fetches_every_upstream_station(conn: Conn) -> None:
    source = FakeSource(readings_before(ISSUED_AT, [10.0]))
    run_hourly(source, conn, CONFIG, ISSUED_AT)
    lookback = timedelta(hours=CONFIG.forecast.upstream_ingest_lookback_hours)
    upstream_count = len(CONFIG.stations) - 1
    assert source.windows[1:] == [(ISSUED_AT - lookback, ISSUED_AT)] * upstream_count


def test_failing_upstream_station_does_not_stop_the_forecast(conn: Conn) -> None:
    readings = FakeSource(readings_before(ISSUED_AT, [10.0, 20.0]))

    def source(station: Station, start: datetime, end: datetime) -> list[Observation]:
        if station.id == "nierenhof":
            raise RuntimeError("portal down")
        return readings(station, start, end)

    result = run_hourly(source, conn, CONFIG, ISSUED_AT)
    langenberg = fetch_observations(conn, "langenberg", LONG_AGO, ISSUED_AT)
    assert result.newest_observation_at == ISSUED_AT.replace(minute=22) and langenberg


def test_failing_forecast_station_fails_the_run(conn: Conn) -> None:
    def source(station: Station, start: datetime, end: datetime) -> list[Observation]:
        raise RuntimeError("influx down")

    with pytest.raises(RuntimeError, match="influx down"):
        run_hourly(source, conn, CONFIG, ISSUED_AT)


def test_fetch_by_source_uses_the_station_source() -> None:
    lanuv_station = CONFIG.station("langenberg")
    fetchers = {"influx": FakeSource({}), "lanuv": FakeSource({})}
    fetch_by_source(fetchers, lanuv_station, LONG_AGO, ISSUED_AT)
    assert (fetchers["influx"].windows, fetchers["lanuv"].windows) == ([], [(LONG_AGO, ISSUED_AT)])


def test_rerun_gives_the_same_forecast(conn: Conn) -> None:
    source = FakeSource(readings_before(ISSUED_AT, [10.0, 20.0]))
    first = run_hourly(source, conn, CONFIG, ISSUED_AT)
    assert run_hourly(source, conn, CONFIG, ISSUED_AT) == first


def test_stale_data_keeps_its_observation_time(conn: Conn) -> None:
    old_reading = ISSUED_AT - timedelta(hours=3, minutes=8)
    backfill(FakeSource({old_reading: 30.0}), conn, STATION, LONG_AGO, ISSUED_AT)
    assert forecast(conn, CONFIG, ISSUED_AT).newest_observation_at == old_reading


def test_forecast_without_any_observation_fails(conn: Conn) -> None:
    with pytest.raises(NoObservationError):
        forecast(conn, CONFIG, ISSUED_AT)


def test_backfill_stores_every_month(conn: Conn) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    readings = {start + timedelta(days=day, minutes=22): 0.1 for day in range(0, 90, 10)}
    backfill(FakeSource(readings), conn, STATION, start, ISSUED_AT)
    stored = fetch_observations(conn, STATION.id, start, ISSUED_AT)
    assert [o.observed_at for o in stored] == sorted(readings)


def test_backfill_twice_adds_nothing(conn: Conn) -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    source = FakeSource(readings_before(ISSUED_AT, [10.0, 20.0, 30.0]))
    backfill(source, conn, STATION, start, ISSUED_AT)
    assert backfill(source, conn, STATION, start, ISSUED_AT) == 0
