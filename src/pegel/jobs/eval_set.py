"""`pegel build-eval-set`: the frozen evaluation dataset and its manifest (docs/decisions/0008).

Reads the jobs database read-only and writes `eval.parquet` and `eval.manifest.json`.
"""

import hashlib
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from pegel.adapters.sources.radolan import load_cells
from pegel.adapters.storage.connection import connect
from pegel.adapters.storage.input_forecasts import fetch_input_forecasts
from pegel.adapters.storage.observations import fetch_values
from pegel.config import PegelConfig, config_file
from pegel.core import issue_inputs
from pegel.core.radar import radar_series
from pegel.core.rain_forecast import catchment_series_id, ring_series_id
from pegel.core.series import cleaned_level_series_id, level_series_id
from pegel.evaluation.contract import GAUGE_PREFIXES, Manifest
from pegel.jobs.pipeline import Conn

DATASET_NAME = "eval.parquet"
# The longest look-back of any input: the 30-day base level, plus the hour of its last window.
LOOK_BACK = timedelta(days=30, hours=1)
# Cleaned values known this much after their time would mean revisions; the plan assumes none.
LATE_AFTER = pd.Timedelta(hours=2)


def build_dataset(
    conn: Conn, config: PegelConfig, first_day: date, last_day: date
) -> tuple[pd.DataFrame, int]:
    """Fetches each series once for the window and builds one row per issue time.

    Also returns how many fetched cleaned values were known more than 2 hours after their time.
    """
    issued_at = issue_inputs.issue_times(first_day, last_day, config.forecast.issue_minute)
    start = issued_at[0].to_pydatetime() - LOOK_BACK
    end = issued_at[-1].to_pydatetime() + timedelta(hours=config.evaluation.leads_hours + 1)

    def observed(series_id: str) -> pd.DataFrame:
        return issue_inputs.observed_frame(fetch_values(conn, series_id, start, end))

    def forecast(series_id: str) -> pd.DataFrame:
        return issue_inputs.forecast_frame(fetch_input_forecasts(conn, series_id, start, end))

    rain = config.rain
    station_id = config.forecast.station_id
    areas = list(load_cells(config_file(rain.radar.cells_file)))
    radar = radar_series(rain.radar.source, areas)
    # Archive first: on a tie in run_at, the live run wins.
    sources = (rain.forecast.archive_source, rain.forecast.source)
    percentile = rain.forecast.ring_percentile
    cleaned = observed(cleaned_level_series_id(station_id))
    upstream = [gauge for gauge in GAUGE_PREFIXES if gauge != station_id]
    dataset = issue_inputs.build_rows(
        issued_at,
        station_id,
        cleaned=cleaned,
        raw=observed(level_series_id(station_id)),
        upstream={gauge: observed(level_series_id(gauge)) for gauge in upstream},
        radar={area: observed(series.id) for area, series in radar.items()},
        icon_mean=pd.concat([forecast(catchment_series_id(source)) for source in sources]),
        icon_p90=pd.concat([forecast(ring_series_id(source, percentile)) for source in sources]),
        leads=config.evaluation.leads_hours,
        target_tolerance=pd.Timedelta(minutes=config.evaluation.target_tolerance_minutes),
    )
    late = int((cleaned["available_at"] > cleaned["valid_at"] + LATE_AFTER).sum())
    return dataset, late


def output_paths(out_dir: Path) -> tuple[Path, Path]:
    """The Parquet file and its manifest; refuses if either exists."""
    path = out_dir / DATASET_NAME
    manifest_path = path.with_suffix(".manifest.json")
    for existing in (path, manifest_path):
        if existing.exists():
            raise SystemExit(f"error: {existing} exists; a frozen dataset is never overwritten")
    return path, manifest_path


def write_dataset(
    dataset: pd.DataFrame,
    paths: tuple[Path, Path],
    config: PegelConfig,
    first_day: date,
    last_day: date,
    git_commit: str,
    database: str,
) -> None:
    """Writes the Parquet file and the manifest next to it."""
    path, manifest_path = paths
    path.parent.mkdir(parents=True, exist_ok=True)
    # pandas loads pyarrow only here; it is in the `analysis` group, not in the Lambda image.
    dataset.to_parquet(path, engine="pyarrow", index=False)
    manifest = Manifest(
        window_first_day=first_day,
        window_last_day=last_day,
        config=config.model_dump(mode="json"),
        git_commit=git_commit,
        row_count=len(dataset),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        created_at=datetime.now(UTC),
        database=database,
    )
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


def run(
    config: PegelConfig, database_url: str, first_day: date, last_day: date, out_dir: Path
) -> None:
    """Builds the dataset from the database read-only, writes it and prints its coverage."""
    # Checked before connecting, so a rerun or a git failure costs no read of the database.
    paths = output_paths(out_dir)
    git_commit = _git_commit()
    with connect_read_only(database_url) as conn:
        dataset, late = build_dataset(conn, config, first_day, last_day)
        database = database_label(conn)
    write_dataset(dataset, paths, config, first_day, last_day, git_commit, database)
    print(coverage_report(dataset))
    print(f"Cleaned values (with look-back) known more than 2 h after their time: {late}")
    print(f"Wrote {len(dataset)} rows to {paths[0]} (database {database})")


def connect_read_only(database_url: str) -> Conn:
    """A connection whose every transaction is READ ONLY, which also holds through Neon's pooler."""
    conn = connect(database_url)
    conn.read_only = True
    return conn


def database_label(conn: Conn) -> str:
    """Role and the host's first label (Neon: the endpoint, which names the branch), no URL."""
    return f"{conn.info.user}/{conn.info.host.split('.')[0]}"


def coverage_report(dataset: pd.DataFrame) -> str:
    """Share of non-missing values per column; windows of one prefix as their min and max."""
    coverage = dataset.notna().mean()
    groups = coverage.groupby(coverage.index.str.replace(r"_\d+$", "", regex=True), sort=False)
    lines = ["Coverage per column (window columns: lowest to highest):"]
    for name, shares in groups:
        if len(shares) == 1:
            lines.append(f"  {name}: {shares.iloc[0]:.1%}")
        else:
            lines.append(f"  {name}_*: {shares.min():.1%} to {shares.max():.1%}")
    return "\n".join(lines)


def _git_commit() -> str:
    """HEAD, marked dirty when the working tree has changes, so the code can be found again."""
    repo = Path(__file__).resolve().parent

    def git(*arguments: str) -> str:
        command = ["git", "-C", str(repo), *arguments]
        return subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip()

    commit = git("rev-parse", "HEAD")
    return f"{commit}-dirty" if git("status", "--porcelain") else commit
