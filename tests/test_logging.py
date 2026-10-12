import io
import json
import logging
import sys
from collections.abc import Iterator

import pytest

from pegel.adapters.logging import JsonLinesFormatter, configure_logging


def format_record(message: str, **extra: object) -> dict[str, object]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLinesFormatter())
    test_logger = logging.getLogger("pegel.test")
    test_logger.handlers = [handler]
    test_logger.propagate = False
    test_logger.warning(message, extra=extra)
    entry: dict[str, object] = json.loads(stream.getvalue())
    return entry


@pytest.fixture
def restore_root_logger() -> Iterator[None]:
    root, httpx_logger = logging.getLogger(), logging.getLogger("httpx")
    handlers, level, httpx_level = root.handlers[:], root.level, httpx_logger.level
    yield
    root.handlers, root.level = handlers, level
    httpx_logger.setLevel(httpx_level)


def test_record_has_standard_fields() -> None:
    entry = format_record("fetched 3 rows")
    assert (entry["level"], entry["logger"], entry["message"]) == (
        "WARNING",
        "pegel.test",
        "fetched 3 rows",
    )


def test_timestamp_is_utc() -> None:
    assert str(format_record("hello")["timestamp"]).endswith("+00:00")


def test_extra_context_is_included() -> None:
    entry = format_record("done", job="run_hourly", station="kupferdreh")
    assert (entry["job"], entry["station"]) == ("run_hourly", "kupferdreh")


def test_exception_is_included() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLinesFormatter())
    test_logger = logging.getLogger("pegel.test.exception")
    test_logger.handlers = [handler]
    test_logger.propagate = False
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        test_logger.exception("failed")
    assert "RuntimeError: boom" in json.loads(stream.getvalue())["exception"]


@pytest.mark.usefixtures("restore_root_logger")
def test_configure_logging_writes_json_to_stdout() -> None:
    configure_logging()
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout


@pytest.mark.usefixtures("restore_root_logger")
def test_configure_logging_silences_httpx_request_lines() -> None:
    configure_logging()
    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
