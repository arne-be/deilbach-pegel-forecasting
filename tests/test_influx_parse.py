import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from pegel.adapters.sources.influx import InfluxError, influx_settings_from_env, parse_levels

FIXTURES = Path(__file__).parent / "fixtures"

VALID_ENV = {
    "INFLUX_URL": "https://influx.example.test",
    "INFLUX_DATABASE": "level",
    "INFLUX_CLIENT_CERT": "/certs/client.crt",
    "INFLUX_CLIENT_KEY": "/certs/client.key",
    "INFLUX_USERNAME": "reader",
    "INFLUX_PASSWORD": "s3cret-value",
}


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_levels_are_converted_from_millimetres_to_metres() -> None:
    observations = parse_levels(load_fixture("influx_levels.json"), "kupferdreh")
    assert [observation.level_m for observation in observations] == [-0.237, -0.25, 0.6845]


def test_timestamps_are_parsed_as_utc() -> None:
    observations = parse_levels(load_fixture("influx_levels.json"), "kupferdreh")
    assert observations[0].observed_at == datetime(2026, 10, 12, 11, 22, 2, tzinfo=UTC)


def test_observations_carry_the_station_id() -> None:
    observations = parse_levels(load_fixture("influx_levels.json"), "kupferdreh")
    assert {observation.station_id for observation in observations} == {"kupferdreh"}


def test_null_levels_are_skipped_and_counted(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        parse_levels(load_fixture("influx_levels.json"), "kupferdreh")
    assert [record.__dict__.get("skipped_rows") for record in caplog.records] == [1]


def test_empty_result_gives_no_observations() -> None:
    assert parse_levels(load_fixture("influx_empty.json"), "kupferdreh") == []


def test_statement_error_raises() -> None:
    with pytest.raises(InfluxError, match="database not found"):
        parse_levels(load_fixture("influx_statement_error.json"), "kupferdreh")


def test_top_level_error_raises() -> None:
    with pytest.raises(InfluxError, match="authorization failed"):
        parse_levels({"error": "authorization failed"}, "kupferdreh")


def test_partial_result_raises() -> None:
    response = {"results": [{"statement_id": 0, "partial": True, "series": []}]}
    with pytest.raises(InfluxError, match="partial"):
        parse_levels(response, "kupferdreh")


@pytest.mark.parametrize(
    "row",
    [
        [1791804122000],
        [1791804122000, "high"],
        ["2026-10-12T11:22:02Z", -237],
        [1791804122000, True],
    ],
)
def test_malformed_row_raises(row: list[Any]) -> None:
    response = {
        "results": [
            {"statement_id": 0, "series": [{"columns": ["time", "level"], "values": [row]}]}
        ]
    }
    with pytest.raises(InfluxError):
        parse_levels(response, "kupferdreh")


def test_missing_level_column_raises() -> None:
    response = {
        "results": [{"statement_id": 0, "series": [{"columns": ["time"], "values": [[1]]}]}]
    }
    with pytest.raises(InfluxError, match="columns"):
        parse_levels(response, "kupferdreh")


def test_settings_are_read_from_the_environment() -> None:
    settings = influx_settings_from_env({**VALID_ENV, "INFLUX_TIMEOUT": "10"})
    assert (settings.url, settings.database, settings.timeout_seconds) == (
        "https://influx.example.test",
        "level",
        10.0,
    )


def test_timeout_defaults_when_unset() -> None:
    assert influx_settings_from_env(VALID_ENV).timeout_seconds == 30.0


def test_missing_variable_is_named() -> None:
    environ = {key: value for key, value in VALID_ENV.items() if key != "INFLUX_PASSWORD"}
    with pytest.raises(ValueError, match="INFLUX_PASSWORD"):
        influx_settings_from_env(environ)


def test_invalid_url_error_does_not_echo_the_value() -> None:
    with pytest.raises(ValueError) as error:
        influx_settings_from_env({**VALID_ENV, "INFLUX_URL": "http://private-host.test"})
    assert "private-host" not in str(error.value)


def test_invalid_timeout_is_rejected() -> None:
    with pytest.raises(ValueError, match="INFLUX_TIMEOUT"):
        influx_settings_from_env({**VALID_ENV, "INFLUX_TIMEOUT": "soon"})


def test_password_is_not_in_repr() -> None:
    assert "s3cret-value" not in repr(influx_settings_from_env(VALID_ENV))
