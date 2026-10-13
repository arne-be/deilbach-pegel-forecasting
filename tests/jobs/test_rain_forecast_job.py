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
from pegel.core.rain_forecast import GridPoint
from pegel.core.schedule import issue_time
from pegel.jobs.rain_forecast import backfill_archive, ingest_new_runs

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
    """Answers metadata, single run and archive requests and records the runs it was asked for.

    Each run gets the recorded run shifted to its start, unless `answers` has (status, body) for it.
    """

    def __init__(
        self, newest: datetime, answers: dict[datetime, tuple[int, Any]] | None = None
    ) -> None:
        self.newest = newest
        self.answers = answers or {}
        self.runs: list[datetime] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url.copy_with(query=None))
        if url == open_meteo.META_URL:
            return httpx.Response(200, json=meta(self.newest))
        if url == open_meteo.ARCHIVE_URL:
            return httpx.Response(200, json=fixture("archive_2024-11-18_19.json"))
        run_at = datetime.fromisoformat(request.url.params["run"]).replace(tzinfo=UTC)
        self.runs.append(run_at)
        status, body = self.answers.get(run_at, (200, run_answer(run_at)))
        return httpx.Response(status, json=body)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(open_meteo, "BACKOFF_BASE_SECONDS", 0)


def meta(run_at: datetime) -> Any:
    return fixture("meta.json") | {"last_run_initialisation_time": int(run_at.timestamp())}


def run_answer(run_at: datetime) -> Any:
    """The recorded run, moved to start at run_at."""
    body = fixture("single_run_2026-10-13T09.json")
    for location in body:
        location["hourly"]["time"] = [
            (datetime.fromisoformat(text) + (run_at - RUN_AT)).strftime("%Y-%m-%dT%H:%M")
            for text in location["hourly"]["time"]
        ]
    return body


def stored(conn: Conn) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT series_id, count(*), min(valid_at - run_at), max(valid_at - run_at)"
        " FROM input_forecasts GROUP BY series_id ORDER BY series_id"
    ).fetchall()


def stored_runs(conn: Conn) -> list[datetime]:
    rows = conn.execute("SELECT DISTINCT run_at FROM input_forecasts ORDER BY 1").fetchall()
    return [row[0].astimezone(UTC) for row in rows]


def runs_back(*hours: int) -> list[datetime]:
    return [RUN_AT - timedelta(hours=back) for back in hours]


def test_catch_up_fetches_missing_runs_newest_first_four_per_hour(conn: Conn) -> None:
    fake = FakeOpenMeteo(RUN_AT)
    with fake.client() as client:
        assert ingest_new_runs(client, conn, SETTINGS, POINTS, MINUTE) == 4 * 96
        assert fake.runs == runs_back(0, 3, 6, 9)
        ingest_new_runs(client, conn, SETTINGS, POINTS, MINUTE)
        ingest_new_runs(client, conn, SETTINGS, POINTS, MINUTE)
    assert fake.runs == runs_back(0, 3, 6, 9, 12, 15, 18, 21, 24)
    assert stored_runs(conn) == sorted(fake.runs)
    assert [row[:2] for row in stored(conn)] == [
        ("open_meteo_icon_d2:catchment:mean", 9 * 48),
        ("open_meteo_icon_d2:ring:p90", 9 * 48),
    ]


def test_only_runs_after_the_newest_stored_are_fetched(conn: Conn) -> None:
    with FakeOpenMeteo(RUN_AT).client() as client:
        for _ in range(3):
            ingest_new_runs(client, conn, SETTINGS, POINTS, MINUTE)
        assert ingest_new_runs(client, conn, SETTINGS, POINTS, MINUTE) == 0
    fake = FakeOpenMeteo(RUN_AT + timedelta(hours=3))
    with fake.client() as client:
        assert ingest_new_runs(client, conn, SETTINGS, POINTS, MINUTE) == 96
        assert ingest_new_runs(client, conn, SETTINGS, POINTS, MINUTE) == 0
    assert fake.runs == [RUN_AT + timedelta(hours=3)]


def test_new_run_is_available_from_the_slot_of_its_fetch(conn: Conn) -> None:
    before = issue_time(datetime.now(UTC), MINUTE)
    with FakeOpenMeteo(RUN_AT).client() as client:
        ingest_new_runs(client, conn, SETTINGS, POINTS, MINUTE)
    row = conn.execute(
        "SELECT min(available_at), max(available_at) FROM input_forecasts"
    ).fetchone()
    assert row is not None and row[0] == row[1]
    assert row[0] in {before, issue_time(datetime.now(UTC), MINUTE)}


def test_failing_run_stops_the_catch_up_but_keeps_earlier_runs(conn: Conn) -> None:
    fake = FakeOpenMeteo(RUN_AT, {RUN_AT - timedelta(hours=6): (503, {})})
    with fake.client() as client:
        assert ingest_new_runs(client, conn, SETTINGS, POINTS, MINUTE) == 2 * 96
    # The failing run was tried twice, the run before it not at all.
    assert fake.runs == runs_back(0, 3, 6, 6)
    assert stored_runs(conn) == runs_back(3, 0)


def test_time_budget_stops_the_catch_up_after_the_newest_run(conn: Conn) -> None:
    seconds = iter([0.0, 60.0, 121.0])  # start, before the second run, before the third
    fake = FakeOpenMeteo(RUN_AT)
    with fake.client() as client:
        changed = ingest_new_runs(
            client, conn, SETTINGS, POINTS, MINUTE, clock=lambda: next(seconds)
        )
    assert changed == 2 * 96
    assert fake.runs == runs_back(0, 3)


def test_data_of_another_run_is_rejected(conn: Conn) -> None:
    fake = FakeOpenMeteo(RUN_AT, {RUN_AT: (200, run_answer(RUN_AT + timedelta(hours=3)))})
    with fake.client() as client:
        assert ingest_new_runs(client, conn, SETTINGS, POINTS, MINUTE) == 0
    assert stored(conn) == []


def test_rate_limit_is_not_retried(conn: Conn) -> None:
    fake = FakeOpenMeteo(RUN_AT, {RUN_AT: (429, {"reason": "Hourly limit"})})
    with fake.client() as client:
        assert ingest_new_runs(client, conn, SETTINGS, POINTS, MINUTE) == 0
    assert fake.runs == [RUN_AT]
    assert stored(conn) == []


def test_archive_backfill_is_idempotent(conn: Conn) -> None:
    fake = FakeOpenMeteo(RUN_AT)
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
    with FakeOpenMeteo(RUN_AT).client() as client:
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
    fake = FakeOpenMeteo(RUN_AT)
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
