import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from pegel.adapters.sources import open_meteo
from pegel.adapters.sources.open_meteo import (
    OpenMeteoError,
    RateLimitedError,
    fetch_archive,
    fetch_forecast,
    latest_run,
    load_points,
    parse_points,
    request_weight,
)
from pegel.config import config_file, load_config
from pegel.core.rain_forecast import (
    GridPoint,
    RunMismatchError,
    archive_values,
    check_run,
    run_values,
)

FIXTURES = Path(__file__).parent / "fixtures" / "open_meteo"
POINTS = [GridPoint(51.3, 7.1, True), GridPoint(51.3, 7.14, True), GridPoint(51.22, 7.02, False)]
RUN_AT = datetime(2026, 10, 13, 9, tzinfo=UTC)
HORIZON = 48
VARIABLES = ["precipitation", "precipitation_previous_day1"]


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def client_answering(*responses: httpx.Response) -> tuple[httpx.Client, list[httpx.Request]]:
    requests: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return queue.pop(0)

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def no_sleep(_: float) -> None:
    pass


def test_points_file_matches_config() -> None:
    points = load_points(config_file(load_config().rain.forecast.points_file))
    assert len(points) == 70
    assert sum(point.in_catchment for point in points) == 9


def test_request_weight_of_one_run_and_one_archive_chunk() -> None:
    assert request_weight(70, 3, 1) == 70
    assert request_weight(70, 14, 2) == 70
    assert request_weight(70, 28, 2) == 140


def test_latest_run_reads_initialisation_time() -> None:
    client, requests = client_answering(httpx.Response(200, json=fixture("meta.json")))
    assert latest_run(client) == RUN_AT
    assert str(requests[0].url) == open_meteo.META_URL


def test_recorded_run_passes_the_run_check_and_gives_48_hours() -> None:
    client, requests = client_answering(
        httpx.Response(200, json=fixture("forecast_run_2026-10-13T09.json"))
    )
    hours = timedelta(hours=1), timedelta(hours=49)
    series = fetch_forecast(client, POINTS, RUN_AT + hours[0], RUN_AT + hours[1])
    check_run(series, RUN_AT, HORIZON)
    values = run_values(
        "open_meteo_icon_d2", series, POINTS, RUN_AT, HORIZON, 90, RUN_AT + timedelta(hours=2)
    )
    assert len(values) == 2 * HORIZON
    assert max(value.valid_at for value in values) == RUN_AT + timedelta(hours=HORIZON)
    params = requests[0].url.params
    assert params["cell_selection"] == "nearest"
    assert params["latitude"] == "51.3,51.3,51.22"


def test_recorded_run_is_rejected_for_an_earlier_run() -> None:
    series = parse_points(fixture("forecast_run_2026-10-13T09.json"), POINTS, ["precipitation"])
    with pytest.raises(RunMismatchError):
        check_run(series["precipitation"], RUN_AT - timedelta(hours=3), HORIZON)


def test_recorded_archive_gives_both_days() -> None:
    client, requests = client_answering(
        httpx.Response(200, json=fixture("archive_2024-11-18_19.json"))
    )
    series = fetch_archive(client, POINTS, VARIABLES, date(2024, 11, 18), date(2024, 11, 19))
    assert requests[0].url.params["start_date"] == "2024-11-18"
    day0 = archive_values(
        "open_meteo_previous_runs", series["precipitation"], POINTS, 0, 90, timedelta(0), 30
    )
    catchment = [value.value for value in day0 if value.series_id.endswith(":catchment:mean")]
    assert len(catchment) == 48
    assert sum(catchment) == pytest.approx((43.2 + 44.3) / 2)


def test_rejects_wrong_number_of_locations() -> None:
    body = fixture("forecast_run_2026-10-13T09.json")[:2]
    with pytest.raises(OpenMeteoError):
        parse_points(body, POINTS, ["precipitation"])


def test_rejects_a_location_off_the_requested_point() -> None:
    body = fixture("forecast_run_2026-10-13T09.json")
    body[2]["longitude"] = 7.04
    with pytest.raises(OpenMeteoError):
        parse_points(body, POINTS, ["precipitation"])


@pytest.mark.parametrize("value", [-0.1, "1.0", True])
def test_rejects_bad_values(value: Any) -> None:
    body = fixture("forecast_run_2026-10-13T09.json")
    body[0]["hourly"]["precipitation"][0] = value
    with pytest.raises(OpenMeteoError):
        parse_points(body, POINTS, ["precipitation"])


def test_rejects_gaps_in_hours() -> None:
    body = fixture("forecast_run_2026-10-13T09.json")
    for location in body:
        del location["hourly"]["time"][5]
        del location["hourly"]["precipitation"][5]
    with pytest.raises(OpenMeteoError):
        parse_points(body, POINTS, ["precipitation"])


def fetch_archive_days(client: httpx.Client) -> dict[str, Any]:
    first, last = date(2024, 11, 18), date(2024, 11, 19)
    return fetch_archive(client, POINTS, VARIABLES, first, last, sleep=no_sleep)


def test_archive_retries_server_errors_then_succeeds() -> None:
    client, requests = client_answering(
        httpx.Response(503), httpx.Response(200, json=fixture("archive_2024-11-18_19.json"))
    )
    assert set(fetch_archive_days(client)) == set(VARIABLES)
    assert len(requests) == 2


def test_archive_gives_up_after_repeated_server_errors() -> None:
    client, requests = client_answering(*[httpx.Response(500)] * open_meteo.MAX_ATTEMPTS)
    with pytest.raises(OpenMeteoError):
        fetch_archive_days(client)
    assert len(requests) == open_meteo.MAX_ATTEMPTS


def test_live_requests_are_not_retried() -> None:
    client, requests = client_answering(httpx.Response(503), httpx.Response(503))
    with pytest.raises(OpenMeteoError):
        latest_run(client)
    with pytest.raises(OpenMeteoError):
        fetch_forecast(client, POINTS, RUN_AT, RUN_AT + timedelta(hours=49))
    assert len(requests) == 2


def test_slowly_trickling_body_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr("pegel.adapters.sources.open_meteo.time.monotonic", lambda: next(clock))
    chunks = [b"{", b'"last_run_initialisation_time"', b": 1791882000}"]

    class Trickle(httpx.SyncByteStream):
        def __iter__(self) -> Any:
            yield from chunks

    client, _ = client_answering(httpx.Response(200, stream=Trickle()))
    with pytest.raises(OpenMeteoError, match="ReadTimeout"):
        latest_run(client)


def test_rate_limit_raises_at_once() -> None:
    answer = httpx.Response(429, json={"error": True, "reason": "Minutely API request limit"})
    client, requests = client_answering(answer)
    with pytest.raises(RateLimitedError, match="Minutely"):
        fetch_forecast(client, POINTS, RUN_AT, RUN_AT + timedelta(hours=49))
    assert len(requests) == 1
