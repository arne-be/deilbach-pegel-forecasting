import hashlib
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import psycopg
import pytest
from eval_factory import radar_areas
from psycopg.rows import TupleRow

from pegel.adapters.storage.input_forecasts import upsert_input_forecasts
from pegel.adapters.storage.observations import upsert_values
from pegel.adapters.storage.series import ensure_series
from pegel.config import load_config
from pegel.core.radar import radar_series
from pegel.core.rain_forecast import forecast_series
from pegel.core.schedule import scheduled_available_at
from pegel.core.series import (
    InputForecastValue,
    SeriesValue,
    cleaned_level_series,
    level_series,
)
from pegel.evaluation import contract
from pegel.jobs import eval_set

Conn = psycopg.Connection[TupleRow]
CONFIG = load_config()
DAY = date(2025, 1, 15)
HOUR = timedelta(hours=1)
START = datetime(2025, 1, 14, 20, tzinfo=UTC)


def seed(conn: Conn) -> None:
    """Hourly readings at :22 from the evening before, radar at :50 and one ICON-D2 run."""
    rain = CONFIG.rain
    radar = radar_series(rain.radar.source, radar_areas())
    stations = [CONFIG.station(name) for name in ("kupferdreh", "langenberg", "nierenhof")]
    icon = forecast_series(rain.forecast.source, rain.forecast.ring_percentile, "test")
    ensure_series(
        conn,
        [level_series(station) for station in stations]
        + [cleaned_level_series(stations[0])]
        + list(radar.values())
        + icon,
    )
    hours = [START + hour * HOUR for hour in range(30)]
    levels = [
        SeriesValue(series.id, at + timedelta(minutes=22), 60.0 + hour, at + HOUR)
        for series in [level_series(s) for s in stations] + [cleaned_level_series(stations[0])]
        for hour, at in enumerate(hours)
    ]
    radar_delay = timedelta(minutes=rain.radar.available_after_minutes)
    rains = [
        SeriesValue(
            series.id,
            at + timedelta(minutes=50),
            float(hour),
            scheduled_available_at(at + timedelta(minutes=50), radar_delay, 30),
            1.0,
        )
        for series in radar.values()
        for hour, at in enumerate(hours)
    ]
    upsert_values(conn, levels + rains, START)
    run_at = datetime(2025, 1, 14, 21, tzinfo=UTC)
    forecasts = [
        InputForecastValue(series.id, run_at, run_at + hour * HOUR, 0.2, run_at + 3 * HOUR)
        for series in icon
        for hour in range(1, 49)
    ]
    upsert_input_forecasts(conn, forecasts, START)


def test_build_eval_set_writes_the_contract_columns_and_manifest(
    conn: Conn, database_url: str, tmp_path: Path
) -> None:
    seed(conn)
    eval_set.run(CONFIG, database_url, DAY, DAY, tmp_path)
    path = tmp_path / eval_set.DATASET_NAME
    dataset = pd.read_parquet(path)
    assert list(dataset.columns) == contract.dataset_columns(radar_areas(), 24)
    assert len(dataset) == 24
    assert dataset[contract.ISSUED_AT][0] == pd.Timestamp("2025-01-15T00:30Z")
    # 00:22 is known from 01:30 on, so at 00:30 the newest known reading is 23:22.
    assert dataset[contract.KD_LAST_AT][0] == pd.Timestamp("2025-01-14T23:22Z")
    assert dataset["target_1"][0] == 65.0
    assert dataset["icon_lead_1"][0] == 3.0
    # The 23:50 product is known from 00:30 on, so it is lag 0 there.
    assert dataset["radar_catchment_lag_0"][0] == 3.0
    assert dataset["radar_catchment_lag_1"][0] == 2.0
    manifest = contract.Manifest.model_validate_json(
        path.with_suffix(".manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.row_count == 24
    assert manifest.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert manifest.config["evaluation"] == CONFIG.evaluation.model_dump(mode="json")
    with pytest.raises(SystemExit):
        eval_set.run(CONFIG, database_url, DAY, DAY, tmp_path)


def test_connection_is_read_only(conn: Conn, database_url: str) -> None:
    seed(conn)
    with (
        eval_set.connect_read_only(database_url) as read_only,
        pytest.raises(psycopg.errors.ReadOnlySqlTransaction),
    ):
        read_only.execute("DELETE FROM observations")
    assert conn.execute("SELECT count(*) FROM observations").fetchone() != (0,)


def test_lambda_handler_imports_without_pyarrow() -> None:
    # pyarrow isn't in the Lambda image; a None entry makes any import of it fail.
    code = "import sys; sys.modules['pyarrow'] = None; import pegel.jobs.lambda_handler"
    subprocess.run([sys.executable, "-c", code], check=True)
