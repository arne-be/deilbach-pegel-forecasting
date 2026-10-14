import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.rows import TupleRow

from pegel.adapters.storage.forecasts import newest_forecast
from pegel.adapters.storage.observations import fetch_observations, fetch_values, upsert_values
from pegel.config import Station, load_config
from pegel.core.observations import Observation
from pegel.core.schedule import issue_time, scheduled_available_at
from pegel.core.series import SeriesValue, cleaned_level_series_id, level_series_id
from pegel.jobs.pipeline import (
    NoObservationError,
    backfill,
    clean,
    clean_history,
    fetch_by_source,
    forecast,
    log_source_delay,
    run_hourly,
)

Conn = psycopg.Connection[TupleRow]
CONFIG = load_config()
STATION = CONFIG.station(CONFIG.forecast.station_id)
ISSUED_AT = datetime(2026, 10, 12, 13, 30, tzinfo=UTC)
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)
MINUTE = CONFIG.forecast.issue_minute


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
    source = FakeSource(readings_before(ISSUED_AT, [-10.0, -15.0, -21.0]))
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
    backfill(FakeSource({old_reading: 30.0}), conn, STATION, LONG_AGO, ISSUED_AT, MINUTE)
    clean(conn, CONFIG, STATION, old_reading, ISSUED_AT)
    assert forecast(conn, CONFIG, ISSUED_AT).newest_observation_at == old_reading


def test_forecast_without_any_observation_fails(conn: Conn) -> None:
    with pytest.raises(NoObservationError):
        forecast(conn, CONFIG, ISSUED_AT)


def test_backfill_stores_every_month(conn: Conn) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    readings = {start + timedelta(days=day, minutes=22): 0.1 for day in range(0, 90, 10)}
    backfill(FakeSource(readings), conn, STATION, start, ISSUED_AT, MINUTE)
    stored = fetch_observations(conn, STATION.id, start, ISSUED_AT)
    assert [o.observed_at for o in stored] == sorted(readings)


def test_backfill_twice_adds_nothing(conn: Conn) -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    source = FakeSource(readings_before(ISSUED_AT, [10.0, 20.0, 30.0]))
    backfill(source, conn, STATION, start, ISSUED_AT, MINUTE)
    assert backfill(source, conn, STATION, start, ISSUED_AT, MINUTE) == 0


def test_extra_steps_run_with_the_issue_time(conn: Conn) -> None:
    calls: list[datetime] = []

    def step(step_conn: Conn, issued_at: datetime) -> int:
        calls.append(issued_at)
        return 0

    run_hourly(
        FakeSource(readings_before(ISSUED_AT, [0.1])), conn, CONFIG, ISSUED_AT, [("rain", step)]
    )
    assert calls == [ISSUED_AT]


def test_failing_extra_step_does_not_stop_the_forecast(conn: Conn) -> None:
    def broken(step_conn: Conn, issued_at: datetime) -> int:
        raise RuntimeError("radar down")

    source = FakeSource(readings_before(ISSUED_AT, [0.1]))
    result = run_hourly(source, conn, CONFIG, ISSUED_AT, [("rain", broken)])
    assert result.issued_at == ISSUED_AT


def available_at(conn: Conn) -> list[datetime]:
    rows = conn.execute(
        "SELECT available_at FROM observations WHERE series_id = %s ORDER BY valid_at",
        (f"{STATION.id}:level",),
    ).fetchall()
    return [row[0] for row in rows]


def test_hourly_run_stamps_new_values_with_the_slot_of_the_fetch(conn: Conn) -> None:
    # A past issue time as with --issued-at: the stamp is still the slot of the fetch.
    before = issue_time(datetime.now(UTC), MINUTE)
    run_hourly(FakeSource(readings_before(ISSUED_AT, [10.0])), conn, CONFIG, ISSUED_AT)
    [stamp] = available_at(conn)
    assert stamp in {before, issue_time(datetime.now(UTC), MINUTE)}


def test_hourly_run_keeps_the_stamp_of_an_unchanged_value(conn: Conn) -> None:
    source = FakeSource(readings_before(ISSUED_AT, [10.0]))
    run_hourly(source, conn, CONFIG, ISSUED_AT)
    first = available_at(conn)
    run_hourly(source, conn, CONFIG, ISSUED_AT)
    assert available_at(conn) == first


def test_backfill_stamps_the_first_scheduled_run_after_the_delay(conn: Conn) -> None:
    readings = readings_before(ISSUED_AT, [10.0, 20.0])
    backfill(FakeSource(readings), conn, STATION, LONG_AGO, ISSUED_AT, MINUTE)
    delay = timedelta(minutes=STATION.available_after_minutes)
    assert available_at(conn) == [
        scheduled_available_at(valid_at, delay, MINUTE) for valid_at in sorted(readings)
    ]


STEADY = [-26.0] * 4
CLEANED_ID = cleaned_level_series_id(STATION.id)


def cleaned_levels(conn: Conn) -> list[float]:
    return [value.value for value in fetch_values(conn, CLEANED_ID, LONG_AGO, ISSUED_AT)]


def test_hourly_run_stores_cleaned_levels_without_the_spike(conn: Conn) -> None:
    source = FakeSource(readings_before(ISSUED_AT, [*STEADY, 298.0, -25.0]))
    run_hourly(source, conn, CONFIG, ISSUED_AT)
    assert cleaned_levels(conn) == [*STEADY, -25.0]


def test_forecast_ignores_a_newest_spike(conn: Conn) -> None:
    source = FakeSource(readings_before(ISSUED_AT, [*STEADY, 298.0]))
    result = run_hourly(source, conn, CONFIG, ISSUED_AT)
    newest_accepted = ISSUED_AT.replace(minute=22) - timedelta(hours=1)
    assert (result.newest_observation_at, result.points[0].level_cm) == (newest_accepted, -26.0)


def test_clean_rerun_changes_nothing(conn: Conn) -> None:
    source = FakeSource(readings_before(ISSUED_AT, [*STEADY, 298.0]))
    backfill(source, conn, STATION, LONG_AGO, ISSUED_AT, MINUTE)
    clean(conn, CONFIG, STATION, LONG_AGO, ISSUED_AT)
    assert clean(conn, CONFIG, STATION, LONG_AGO, ISSUED_AT) == 0


def test_reading_rejected_on_rerun_is_deleted(conn: Conn) -> None:
    readings = readings_before(ISSUED_AT, [*STEADY, -25.0])
    backfill(FakeSource(readings), conn, STATION, LONG_AGO, ISSUED_AT, MINUTE)
    clean(conn, CONFIG, STATION, LONG_AGO, ISSUED_AT)
    newest = max(readings)
    raw_id = level_series_id(STATION.id)
    upsert_values(conn, [SeriesValue(raw_id, newest, 298.0, newest)], ISSUED_AT)
    clean(conn, CONFIG, STATION, LONG_AGO, ISSUED_AT)
    assert cleaned_levels(conn) == STEADY


def test_clean_history_covers_every_month(conn: Conn) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    readings = {start + timedelta(days=day, minutes=22): -26.0 for day in range(0, 90, 10)}
    backfill(FakeSource(readings), conn, STATION, start, ISSUED_AT, MINUTE)
    clean_history(conn, CONFIG, STATION, start, ISSUED_AT)
    assert [value.valid_at for value in fetch_values(conn, CLEANED_ID, start, ISSUED_AT)] == sorted(
        readings
    )


def delay_logs(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [vars(record) for record in caplog.records if record.getMessage() == "source delay"]


def test_source_delay_is_fetch_time_minus_newest_timestamp(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    fetched_at = ISSUED_AT + timedelta(minutes=1)
    log_source_delay("influx", "kupferdreh", fetched_at, ISSUED_AT.replace(minute=22), ISSUED_AT)
    [entry] = delay_logs(caplog)
    assert (entry["delay_minutes"], entry["empty"], entry["rerun"]) == (9, False, False)


def test_empty_fetch_logs_no_delay(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    log_source_delay("lanuv", "langenberg", ISSUED_AT, None)
    [entry] = delay_logs(caplog)
    assert (entry["newest_at"], entry["delay_minutes"], entry["empty"]) == (None, None, True)


def test_rerun_of_a_past_issue_time_is_marked(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    log_source_delay("influx", "kupferdreh", ISSUED_AT + timedelta(days=1), ISSUED_AT, ISSUED_AT)
    assert [entry["rerun"] for entry in delay_logs(caplog)] == [True]


def test_hourly_run_logs_a_delay_per_station(conn: Conn, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    run_hourly(FakeSource(readings_before(ISSUED_AT, [10.0])), conn, CONFIG, ISSUED_AT)
    logged = sorted(entry["series"] for entry in delay_logs(caplog))
    assert logged == sorted(station.id for station in CONFIG.stations)


def test_backfill_logs_no_delay(conn: Conn, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    source = FakeSource(readings_before(ISSUED_AT, [10.0]))
    backfill(source, conn, STATION, ISSUED_AT - timedelta(days=1), ISSUED_AT, MINUTE)
    assert delay_logs(caplog) == []
