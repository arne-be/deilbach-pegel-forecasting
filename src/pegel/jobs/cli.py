"""Command line entry point for local runs: `pegel backfill` and `pegel run-hourly`."""

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from functools import partial
from zoneinfo import ZoneInfo

import httpx

from pegel.adapters.env_files import load_env_files, main_checkout
from pegel.adapters.logging import configure_logging
from pegel.adapters.sources.influx import fetch_levels, influx_settings_from_env, ssl_context
from pegel.adapters.storage.connection import connect
from pegel.config import PegelConfig, load_config
from pegel.core.forecasts import Forecast
from pegel.core.schedule import issue_time
from pegel.core.summary import summarize
from pegel.jobs.pipeline import FetchLevels, backfill, run_hourly

DISPLAY_TIME_ZONE = ZoneInfo("Europe/Berlin")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    configure_logging()
    load_env_files(main_checkout())
    config = load_config()
    database_url = _required_env("JOBS_DATABASE_URL")
    influx_settings = influx_settings_from_env(os.environ)
    with (
        httpx.Client(verify=ssl_context(influx_settings)) as client,
        connect(database_url) as conn,
    ):
        # Each storage call commits on its own, so a failed backfill month keeps the others.
        conn.autocommit = True
        fetch: FetchLevels = partial(fetch_levels, influx_settings, client=client)
        if arguments.command == "backfill":
            station = config.station(config.forecast.station_id)
            start = _utc_midnight(arguments.start)
            end = _utc_midnight(arguments.end) if arguments.end else datetime.now(UTC)
            changed = backfill(fetch, conn, station, start, end)
            print(f"Backfill {start:%Y-%m-%d} to {end:%Y-%m-%d %H:%M} UTC: {changed} rows stored")
            return 0
        issued_at = arguments.issued_at or issue_time(
            datetime.now(UTC), config.forecast.issue_minute
        )
        print(_describe(run_hourly(fetch, conn, config, issued_at), config))
        return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pegel")
    commands = parser.add_subparsers(dest="command", required=True)
    backfill_parser = commands.add_parser("backfill", help="load history in monthly chunks")
    backfill_parser.add_argument("--source", choices=["influx"], required=True)
    backfill_parser.add_argument(
        "--from", dest="start", type=date.fromisoformat, required=True, help="UTC date"
    )
    backfill_parser.add_argument(
        "--to", dest="end", type=date.fromisoformat, help="UTC date, exclusive (default: now)"
    )
    hourly_parser = commands.add_parser("run-hourly", help="ingest recent hours and forecast")
    hourly_parser.add_argument(
        "--issued-at",
        type=_utc_datetime,
        help="ISO time with offset, e.g. 2026-10-12T13:30Z (default: latest scheduled run)",
    )
    return parser


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"error: {name} is not set (check .env.local)")
    return value


def _utc_midnight(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=UTC)


def _utc_datetime(text: str) -> datetime:
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("give a time zone, e.g. 2026-10-12T13:30Z")
    return parsed.astimezone(UTC)


def _describe(forecast: Forecast, config: PegelConfig) -> str:
    def local(moment: datetime) -> str:
        return f"{moment.astimezone(DISPLAY_TIME_ZONE):%d.%m.%Y %H:%M}"

    lines = [
        f"Forecast ({forecast.model}) issued {local(forecast.issued_at)} Europe/Berlin, "
        f"newest observation {local(forecast.newest_observation_at)}",
    ]
    for summary in summarize(forecast, config.forecast.summary_horizons_hours, config.categories):
        lines.append(
            f"  next {summary.horizon_hours:>2} h: max {summary.max_level_m:.2f} m "
            f"at {local(summary.valid_at_of_max)} -> category {summary.category.number} "
            f"({summary.category.name})"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
