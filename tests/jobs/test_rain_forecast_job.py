import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from psycopg.rows import TupleRow

from pegel.adapters.sources import open_meteo
from pegel.config import load_config
from pegel.core.rain_forecast import GridPoint, RunMismatchError
from pegel.core.schedule import issue_time
from pegel.jobs.rain_forecast import backfill_archive, ingest_newest_run

Conn = psycopg.Connection[TupleRow]
SETTINGS = load_config().rain.forecast
MINUTE = load_config().forecast.issue_minute
FIXTURES = Path(__file__).parents[1] / "fixtures" / "open_meteo"
POINTS = [GridPoint(51.3, 7.1, True), GridPoint(51.3, 7.14, True), GridPoint(51.22, 7.02, False)]
RUN_AT = datetime(2026, 10, 13, 9, tzinfo=UTC)
LONG_AFTER = datetime(2026, 10, 13, 12, tzinfo=UTC)


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeOpenMeteo:
    """Answers metadata, forecast and archive requests and records the URLs it was asked for."""

    def __init__(self, metas: list[dict[str, Any]], forecast: httpx.Response) -> None:
        self.metas = metas
        self.forecast = forecast
        self.urls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url.copy_with(query=None))
        self.urls.append(url)
        if url == open_meteo.META_URL:
            return httpx.Response(
                200, json=self.metas.pop(0) if len(self.metas) > 1 else self.metas[0]
            )
        if url == open_meteo.ARCHIVE_URL:
            return httpx.Response(200, json=fixture("archive_2024-11-18_19.json"))
        return self.forecast

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def meta(run_at: datetime) -> Any:
    return fixture("meta.json") | {"last_run_initialisation_time": int(run_at.timestamp())}


def forecast_ok() -> httpx.Response:
    return httpx.Response(200, json=fixture("forecast_run_2026-10-13T09.json"))


def stored(conn: Conn) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT series_id, count(*), min(valid_at - run_at), max(valid_at - run_at)"
        " FROM input_forecasts GROUP BY series_id ORDER BY series_id"
    ).fetchall()


def test_new_run_is_stored_once(conn: Conn) -> None:
    fake = FakeOpenMeteo([meta(RUN_AT)], forecast_ok())
    with fake.client() as client:
        assert ingest_newest_run(client, conn, SETTINGS, POINTS, MINUTE) == 96
        assert [row[:2] for row in stored(conn)] == [
            ("open_meteo_icon_d2:catchment:mean", 48),
            ("open_meteo_icon_d2:ring:p90", 48),
        ]
        requests_before = len(fake.urls)
        assert ingest_newest_run(client, conn, SETTINGS, POINTS, MINUTE) == 0
    # The rerun only read the metadata.
    assert fake.urls[requests_before:] == [open_meteo.META_URL]


def test_new_run_is_available_from_the_slot_of_its_fetch(conn: Conn) -> None:
    before = issue_time(datetime.now(UTC), MINUTE)
    with FakeOpenMeteo([meta(RUN_AT)], forecast_ok()).client() as client:
        ingest_newest_run(client, conn, SETTINGS, POINTS, MINUTE)
    row = conn.execute(
        "SELECT min(available_at), max(available_at) FROM input_forecasts"
    ).fetchone()
    assert row is not None and row[0] == row[1]
    assert row[0] in {before, issue_time(datetime.now(UTC), MINUTE)}


def test_run_published_during_fetch_is_not_stored(conn: Conn) -> None:
    later_run = datetime(2026, 10, 13, 12, tzinfo=UTC)
    fake = FakeOpenMeteo([meta(RUN_AT), meta(later_run)], forecast_ok())
    with fake.client() as client:
        assert ingest_newest_run(client, conn, SETTINGS, POINTS, MINUTE) == 0
    assert stored(conn) == []


def test_data_of_another_run_is_rejected(conn: Conn) -> None:
    earlier_run = datetime(2026, 10, 13, 6, tzinfo=UTC)
    fake = FakeOpenMeteo([meta(earlier_run)], forecast_ok())
    with fake.client() as client, pytest.raises(RunMismatchError):
        ingest_newest_run(client, conn, SETTINGS, POINTS, MINUTE)
    assert stored(conn) == []


def test_rate_limit_skips_the_run(conn: Conn) -> None:
    fake = FakeOpenMeteo([meta(RUN_AT)], httpx.Response(429, json={"reason": "Hourly limit"}))
    with fake.client() as client:
        assert ingest_newest_run(client, conn, SETTINGS, POINTS, MINUTE) == 0
    assert stored(conn) == []


def test_archive_backfill_is_idempotent(conn: Conn) -> None:
    fake = FakeOpenMeteo([meta(RUN_AT)], forecast_ok())
    first, end = date(2024, 11, 18), date(2024, 11, 20)
    with fake.client() as client:
        result = backfill_archive(
            client, conn, SETTINGS, POINTS, first, end, MINUTE, now=LONG_AFTER
        )
        rerun = backfill_archive(client, conn, SETTINGS, POINTS, first, end, MINUTE, now=LONG_AFTER)
    # 48 hours, two variables, two series.
    assert (result.changed, result.calls, result.resume_from) == (192, 3, None)
    assert rerun.changed == 0
    rows = {row[0]: row[1:] for row in stored(conn)}
    count, shortest, longest = rows["open_meteo_previous_runs:catchment:mean"]
    assert count == 96
    assert (shortest.total_seconds(), longest.total_seconds()) == (3600, 27 * 3600)


def test_archive_runs_are_available_at_the_first_hourly_run_after_the_delay(conn: Conn) -> None:
    with FakeOpenMeteo([meta(RUN_AT)], forecast_ok()).client() as client:
        first, end = date(2024, 11, 18), date(2024, 11, 20)
        backfill_archive(client, conn, SETTINGS, POINTS, first, end, 30, now=LONG_AFTER)
    delays = conn.execute(
        "SELECT DISTINCT available_at - run_at FROM input_forecasts ORDER BY 1"
    ).fetchall()
    # Runs start on the hour, so with 120 minutes the :30 run after next takes them.
    assert SETTINGS.available_after_minutes == 120
    assert delays == [(timedelta(minutes=150),)]


def test_archive_backfill_stops_at_the_call_budget(conn: Conn, monkeypatch: Any) -> None:
    monkeypatch.setattr("pegel.jobs.rain_forecast.ARCHIVE_MAX_CALLS", 4)
    fake = FakeOpenMeteo([meta(RUN_AT)], forecast_ok())
    sleeps: list[float] = []
    with fake.client() as client:
        result = backfill_archive(
            client,
            conn,
            SETTINGS,
            POINTS,
            date(2024, 11, 1),
            date(2024, 12, 1),
            MINUTE,
            now=LONG_AFTER,
            sleep=sleeps.append,
        )
    assert result.resume_from == date(2024, 11, 15)
    assert result.calls == 3
    assert sleeps == []
