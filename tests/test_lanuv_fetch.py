import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from pegel.adapters.sources.lanuv import LanuvError, fetch_levels, parse_week
from pegel.config import Station

FIXTURES = Path(__file__).parent / "fixtures"
WEEK_BODY = json.loads((FIXTURES / "lanuv_week.json").read_text(encoding="utf-8"))

STATION = Station(
    id="nierenhof", name="Felderbach Nierenhof", source="lanuv", source_label="2769649000100"
)
# The fixture's readings are 08:50, 08:55, 09:00 and 09:05 UTC.
START = datetime(2026, 10, 13, 8, 55, tzinfo=UTC)
END = datetime(2026, 10, 13, 9, 5, tzinfo=UTC)


def week_with(**changes: Any) -> list[dict[str, Any]]:
    return [{**WEEK_BODY[0], **changes}]


class Recorder:
    """Answers requests with a fixed sequence of responses and remembers what was asked."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def fetch(self) -> list[datetime]:
        client = httpx.Client(transport=httpx.MockTransport(self.handle))
        observations = fetch_levels(STATION, START, END, client, sleep=self.sleeps.append)
        return [observation.observed_at for observation in observations]


def ok() -> httpx.Response:
    return httpx.Response(200, json=WEEK_BODY)


def test_readings_are_parsed_to_metres_and_utc() -> None:
    first = parse_week(WEEK_BODY, STATION)[0]
    assert (first.station_id, first.observed_at) == (
        "nierenhof",
        datetime(2026, 10, 13, 8, 50, tzinfo=UTC),
    )
    assert first.level_m == pytest.approx(0.14)


def test_gaps_are_skipped() -> None:
    body = week_with(data=[["2026-10-13T09:50:00.000+01:00", None]])
    assert parse_week(body, STATION) == []


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (week_with(ts_unitsymbol="m"), "unit"),
        (week_with(station_no="2769630000200"), "station"),
        (WEEK_BODY * 2, "exactly one"),
        (week_with(data=[["2026-10-13T09:50:00.000+01:00"]]), "malformed"),
        (week_with(data=[["2026-10-13T09:50:00.000+01:00", "14.0"]]), "not a number"),
        (week_with(data=[["2026-10-13T09:50:00", 14.0]]), "timestamp"),
    ],
)
def test_unexpected_answers_are_rejected(body: Any, message: str) -> None:
    with pytest.raises(LanuvError, match=message):
        parse_week(body, STATION)


def test_fetch_keeps_only_the_half_open_window() -> None:
    assert Recorder(ok()).fetch() == [
        datetime(2026, 10, 13, 8, 55, tzinfo=UTC),
        datetime(2026, 10, 13, 9, 0, tzinfo=UTC),
    ]


def test_fetch_asks_for_the_station_week() -> None:
    recorder = Recorder(ok())
    recorder.fetch()
    request = recorder.requests[0]
    assert request.method == "GET"
    assert request.url.path == "/data/internet/stations/100/2769649000100/S/week.json"


def test_server_error_is_retried_with_backoff() -> None:
    recorder = Recorder(httpx.Response(503), httpx.ConnectError("refused"), ok())
    recorder.fetch()
    assert recorder.sleeps == [2.0, 4.0]


def test_gives_up_after_three_failed_attempts() -> None:
    recorder = Recorder(httpx.Response(500), httpx.Response(500), httpx.Response(500))
    with pytest.raises(LanuvError, match="3 attempts"):
        recorder.fetch()


def test_not_found_is_not_retried() -> None:
    recorder = Recorder(httpx.Response(404), ok())
    with pytest.raises(LanuvError, match="404"):
        recorder.fetch()
    assert len(recorder.requests) == 1


def test_non_json_body_raises() -> None:
    with pytest.raises(LanuvError, match="not JSON"):
        Recorder(httpx.Response(200, text="<html>maintenance</html>")).fetch()
