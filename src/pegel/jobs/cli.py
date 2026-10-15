"""Command line entry point for local runs: `backfill`, `backfill-*`, `clean`, `run-hourly`,
`build-eval-set`, `train-model`."""

import argparse
import os
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime, time
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from pegel.adapters.env_files import load_env_files, main_checkout
from pegel.adapters.logging import configure_logging
from pegel.adapters.sources import lanuv, open_meteo
from pegel.adapters.sources.influx import fetch_levels, influx_settings_from_env, ssl_context
from pegel.adapters.sources.lanuv_files import LevelFiles
from pegel.adapters.storage.connection import connect
from pegel.config import PegelConfig, config_file, load_config
from pegel.core.forecasts import Forecast
from pegel.core.schedule import issue_time
from pegel.core.summary import summarize
from pegel.jobs import rain_forecast
from pegel.jobs.pipeline import (
    Conn,
    FetchLevels,
    HourlyStep,
    backfill,
    clean_history,
    fetch_by_source,
    run_hourly,
)
from pegel.jobs.radar import backfill_radar, radar_step

DISPLAY_TIME_ZONE = ZoneInfo("Europe/Berlin")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    configure_logging()
    load_env_files(main_checkout())
    config = load_config()
    if arguments.command == "backfill-forecast":
        end = arguments.end or datetime.now(UTC).date()
        return _backfill_forecast(config, arguments.start, end)
    if arguments.command == "backfill-radar":
        _backfill_radar(config, arguments)
        return 0
    if arguments.command == "backfill":
        start = _utc_midnight(arguments.start)
        end = _utc_midnight(arguments.end) if arguments.end else datetime.now(UTC)
        if arguments.source == "lanuv-files":
            _backfill_lanuv_files(config, arguments.path, arguments.station, start, end)
            return 0
        station = config.station(config.forecast.station_id)
        with sources_from_env() as (fetch, conn):
            changed = backfill(fetch, conn, station, start, end, config.forecast.issue_minute)
        print(f"Backfill {start:%Y-%m-%d} to {end:%Y-%m-%d %H:%M} UTC: {changed} rows stored")
        return 0
    if arguments.command == "build-eval-set":
        # Lazy: the Lambda imports this module, and the dataset build isn't part of it.
        from pegel.jobs import eval_set

        database_url = _required_env("JOBS_DATABASE_URL")
        eval_set.run(config, database_url, arguments.start, arguments.end, arguments.out)
        return 0
    if arguments.command == "train-model":
        # Lazy, like build-eval-set: training isn't part of the Lambda.
        from pegel.jobs import train

        evaluation = config.evaluation
        train.run(
            config,
            _required_env("JOBS_DATABASE_URL"),
            arguments.model,
            arguments.start or evaluation.window_first_day,
            arguments.end or evaluation.window_last_day,
            arguments.out,
            arguments.bucket,
        )
        return 0
    if arguments.command == "clean":
        _clean_history(config, arguments.start, arguments.end)
        return 0
    print(_describe(run_hourly_from_env(config, arguments.issued_at), config))
    return 0


def run_hourly_from_env(config: PegelConfig, issued_at: datetime | None = None) -> Forecast:
    """The hourly run, as scheduled. Without an issue time, it uses the latest scheduled run."""
    issued_at = issued_at or issue_time(datetime.now(UTC), config.forecast.issue_minute)
    with (
        sources_from_env() as (fetch, conn),
        httpx.Client() as dwd_client,
        httpx.Client() as open_meteo_client,
    ):
        # Extra inputs such as rain register here as (job name, step).
        extra_steps: list[tuple[str, HourlyStep]] = [
            ("radar_rain", radar_step(config, dwd_client)),
            (
                "rain_forecast",
                rain_forecast.hourly_step(
                    open_meteo_client, config.rain.forecast, config.forecast.issue_minute
                ),
            ),
        ]
        return run_hourly(fetch, conn, config, issued_at, extra_steps)


@contextmanager
def sources_from_env() -> Iterator[tuple[FetchLevels, Conn]]:
    """All sources, each picked by `station.source`, and the jobs database, set up from env."""
    database_url = _required_env("JOBS_DATABASE_URL")
    influx_settings = influx_settings_from_env(os.environ)
    with (
        httpx.Client(verify=ssl_context(influx_settings)) as client,
        httpx.Client() as lanuv_client,
        connect(database_url) as conn,
    ):
        # Each storage call commits on its own, so a failed backfill month keeps the others.
        conn.autocommit = True
        fetchers: dict[str, FetchLevels] = {
            "influx": partial(fetch_levels, influx_settings, client=client),
            "lanuv": partial(lanuv.fetch_levels, client=lanuv_client),
        }
        yield partial(fetch_by_source, fetchers), conn


def _backfill_lanuv_files(
    config: PegelConfig,
    directory: Path | None,
    station_id: str | None,
    start: datetime,
    end: datetime,
) -> None:
    """Backfills LANUV stations from open data files. Needs only the database, no Influx."""
    stations = [
        station
        for station in config.stations
        if station.source == "lanuv" and station_id in (None, station.id)
    ]
    if directory is None or not stations:
        raise SystemExit("error: lanuv-files needs --path and, if given, a LANUV --station")
    fetch = LevelFiles(directory)
    with connect(_required_env("JOBS_DATABASE_URL")) as conn:
        conn.autocommit = True
        for station in stations:
            changed = backfill(fetch, conn, station, start, end, config.forecast.issue_minute)
            print(
                f"Backfill {station.id} {start:%Y-%m-%d} to {end:%Y-%m-%d}: {changed} rows stored"
            )


def _backfill_forecast(config: PegelConfig, start: date, end: date) -> int:
    """Loads the ICON-D2 forecast archive. Needs only the database and Open-Meteo."""
    settings = config.rain.forecast
    points = open_meteo.load_points(config_file(settings.points_file))
    with httpx.Client() as client, connect(_required_env("JOBS_DATABASE_URL")) as conn:
        conn.autocommit = True
        issue_minute = config.forecast.issue_minute
        result = rain_forecast.backfill_archive(
            client, conn, settings, points, start, end, issue_minute, now=datetime.now(UTC)
        )
    loaded_until = result.resume_from or end
    print(
        f"Forecast archive {start} to {loaded_until} (exclusive): {result.changed} rows stored, "
        f"about {result.calls:.0f} Open-Meteo calls"
    )
    if result.resume_from is None:
        return 0
    print(f"Stopped early (call budget or rate limit). Resume with --from {result.resume_from}")
    return 1


def _backfill_radar(config: PegelConfig, arguments: argparse.Namespace) -> None:
    """Backfills radar rain from DWD's archives. Needs only the database, no Influx."""
    start = _utc_midnight(arguments.start)
    end = _utc_midnight(arguments.end) if arguments.end else datetime.now(UTC)
    with connect(_required_env("JOBS_DATABASE_URL")) as conn, httpx.Client() as client:
        conn.autocommit = True
        changed = backfill_radar(conn, config, client, start, end, arguments.cache_dir)
    print(f"Radar backfill {start:%Y-%m-%d} to {end:%Y-%m-%d %H:%M} UTC: {changed} rows stored")


def _clean_history(config: PegelConfig, first_day: date, end_day: date | None) -> None:
    """Rewrites the cleaned levels of the forecast station. Needs only the database."""
    start = _utc_midnight(first_day)
    end = _utc_midnight(end_day) if end_day else datetime.now(UTC)
    station = config.station(config.forecast.station_id)
    with connect(_required_env("JOBS_DATABASE_URL")) as conn:
        conn.autocommit = True
        changed = clean_history(conn, config, station, start, end)
    print(
        f"Clean {station.id} {start:%Y-%m-%d} to {end:%Y-%m-%d %H:%M} UTC: {changed} rows changed"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pegel")
    commands = parser.add_subparsers(dest="command", required=True)
    backfill_parser = commands.add_parser("backfill", help="load history in monthly chunks")
    backfill_parser.add_argument("--source", choices=["influx", "lanuv-files"], required=True)
    backfill_parser.add_argument(
        "--path", type=Path, help="lanuv-files: folder with the extracted LANUV level CSV files"
    )
    backfill_parser.add_argument(
        "--station", help="lanuv-files: one station id (default: all LANUV stations)"
    )
    backfill_parser.add_argument(
        "--from", dest="start", type=date.fromisoformat, required=True, help="UTC date"
    )
    backfill_parser.add_argument(
        "--to", dest="end", type=date.fromisoformat, help="UTC date, exclusive (default: now)"
    )
    forecast_parser = commands.add_parser(
        "backfill-forecast", help="load the ICON-D2 rain forecast archive from Open-Meteo"
    )
    forecast_parser.add_argument(
        "--from", dest="start", type=date.fromisoformat, required=True, help="UTC date"
    )
    forecast_parser.add_argument(
        "--to", dest="end", type=date.fromisoformat, help="UTC date, exclusive (default: today)"
    )
    radar_parser = commands.add_parser("backfill-radar", help="load radar rain from DWD archives")
    radar_parser.add_argument(
        "--from", dest="start", type=date.fromisoformat, required=True, help="UTC date"
    )
    radar_parser.add_argument(
        "--to", dest="end", type=date.fromisoformat, help="UTC date, exclusive (default: now)"
    )
    radar_parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / ".cache" / "deilbach-pegel" / "radolan",
        help="where downloaded DWD files are kept (default: %(default)s)",
    )
    clean_parser = commands.add_parser(
        "clean", help="rewrite the cleaned levels of the forecast station in monthly chunks"
    )
    clean_parser.add_argument(
        "--from", dest="start", type=date.fromisoformat, required=True, help="UTC date"
    )
    clean_parser.add_argument(
        "--to", dest="end", type=date.fromisoformat, help="UTC date, exclusive (default: now)"
    )
    eval_parser = commands.add_parser(
        "build-eval-set", help="build the evaluation dataset, reading the database read-only"
    )
    eval_parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    eval_parser.add_argument(
        "--to", dest="end", type=date.fromisoformat, required=True, help="UTC date, inclusive"
    )
    eval_parser.add_argument("--out", type=Path, required=True, help="folder outside the repo")
    train_parser = commands.add_parser(
        "train-model", help="fit a model on the window and save it, reading the database read-only"
    )
    train_parser.add_argument(
        "--model", required=True, help="registered name, e.g. ridge:change:v2"
    )
    train_parser.add_argument(
        "--from", dest="start", type=date.fromisoformat, help="UTC date (default: eval window)"
    )
    train_parser.add_argument(
        "--to",
        dest="end",
        type=date.fromisoformat,
        help="UTC date, inclusive (default: eval window)",
    )
    train_parser.add_argument("--out", type=Path, required=True, help="folder outside the repo")
    train_parser.add_argument("--bucket", help="also upload to s3://<bucket>/models/")
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
            f"  next {summary.horizon_hours:>2} h: max {summary.max_level_cm:.1f} cm "
            f"at {local(summary.valid_at_of_max)} -> category {summary.category.number} "
            f"({summary.category.name})"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
