import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from pegel.adapters.sources.influx import InfluxError, InfluxSettings, fetch_levels
from pegel.config import Station

FIXTURES = Path(__file__).parent / "fixtures"
LEVELS_BODY = json.loads((FIXTURES / "influx_levels.json").read_text(encoding="utf-8"))

SETTINGS = InfluxSettings(
    url="https://influx.example.test",
    database="level",
    client_cert=Path("/certs/client.crt"),
    client_key=Path("/certs/client.key"),
    username="reader",
    password="s3cret-value",
    timeout_seconds=5,
)
STATION = Station(
    id="kupferdreh", name="Deilbach Kupferdreh", source="influx", source_label="Deilbach"
)
START = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)
END = datetime(2026, 10, 12, 16, 0, tzinfo=UTC)


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

    def fetch(self) -> list[object]:
        client = httpx.Client(transport=httpx.MockTransport(self.handle))
        return list(fetch_levels(SETTINGS, STATION, START, END, client, sleep=self.sleeps.append))


def ok() -> httpx.Response:
    return httpx.Response(200, json=LEVELS_BODY)


def test_successful_fetch_returns_observations() -> None:
    assert len(Recorder(ok()).fetch()) == 3


def test_server_error_is_retried_with_backoff() -> None:
    recorder = Recorder(httpx.Response(503), httpx.Response(502), ok())
    recorder.fetch()
    assert recorder.sleeps == [2.0, 4.0]


def test_network_error_is_retried() -> None:
    recorder = Recorder(httpx.ConnectError("refused"), ok())
    recorder.fetch()
    assert len(recorder.requests) == 2


def test_gives_up_after_three_failed_attempts() -> None:
    recorder = Recorder(httpx.Response(500), httpx.Response(500), httpx.Response(500))
    with pytest.raises(InfluxError, match="3 attempts"):
        recorder.fetch()


def test_unauthorized_is_not_retried() -> None:
    recorder = Recorder(httpx.Response(401), ok())
    with pytest.raises(InfluxError, match="401"):
        recorder.fetch()
    assert len(recorder.requests) == 1


def test_error_in_ok_body_raises() -> None:
    body = {"results": [{"statement_id": 0, "error": "error parsing query"}]}
    with pytest.raises(InfluxError, match="error parsing query"):
        Recorder(httpx.Response(200, json=body)).fetch()


def test_non_json_body_raises() -> None:
    with pytest.raises(InfluxError, match="not JSON"):
        Recorder(httpx.Response(200, text="<html>proxy error</html>")).fetch()


def test_basic_auth_header_is_sent() -> None:
    recorder = Recorder(ok())
    recorder.fetch()
    expected = base64.b64encode(b"reader:s3cret-value").decode()
    assert recorder.requests[0].headers["authorization"] == f"Basic {expected}"


def test_credentials_are_not_in_the_url() -> None:
    recorder = Recorder(ok())
    recorder.fetch()
    url = str(recorder.requests[0].url)
    assert "reader" not in url and "s3cret" not in url


def test_only_get_on_query_is_used() -> None:
    recorder = Recorder(ok())
    recorder.fetch()
    request = recorder.requests[0]
    assert (request.method, request.url.path) == ("GET", "/query")


def test_label_and_window_are_bind_parameters() -> None:
    recorder = Recorder(ok())
    recorder.fetch()
    query = recorder.requests[0].url.params
    assert "Deilbach" not in query["q"] and json.loads(query["params"]) == {
        "label": "Deilbach",
        "start": "2026-10-12T10:00:00.000000Z",
        "end": "2026-10-12T16:00:00.000000Z",
    }


def test_window_is_half_open_in_the_query() -> None:
    recorder = Recorder(ok())
    recorder.fetch()
    query = recorder.requests[0].url.params["q"]
    assert "time >= $start" in query and "time < $end" in query


@pytest.mark.parametrize(
    ("start", "end"), [(END, START), (START, START), (START.replace(tzinfo=None), END)]
)
def test_invalid_window_is_rejected(start: datetime, end: datetime) -> None:
    with pytest.raises(ValueError):
        fetch_levels(SETTINGS, STATION, start, end, httpx.Client())
