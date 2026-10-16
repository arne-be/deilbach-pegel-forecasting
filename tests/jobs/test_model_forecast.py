"""The hourly run with a trained model next to persistence, and the model file."""

import logging
from datetime import UTC, datetime, timedelta

import numpy as np
import numpy.typing as npt
import pandas as pd
import psycopg
import pytest
from psycopg.rows import TupleRow

from pegel.adapters.model_files import TrainedModel, model_from_file
from pegel.adapters.storage.forecasts import newest_forecast
from pegel.adapters.storage.input_forecasts import upsert_input_forecasts
from pegel.adapters.storage.series import ensure_series
from pegel.config import Station, load_config
from pegel.core import bands
from pegel.core.observations import Observation
from pegel.core.rain_forecast import forecast_series
from pegel.core.schedule import issue_time
from pegel.core.series import InputForecastValue
from pegel.evaluation import contract
from pegel.evaluation.models.curated import RIDGE_V2, RIDGE_V2_ALPHA, CuratedChange
from pegel.jobs.pipeline import run_hourly

Conn = psycopg.Connection[TupleRow]
CONFIG = load_config()
RIDGE = "ridge:change:v2"
RIDGE_CONFIG = CONFIG.model_copy(
    update={"forecast": CONFIG.forecast.model_copy(update={"model": RIDGE, "model_file": "m"})}
)
# Now, since a live ingest stamps readings as known from the current slot on.
ISSUED_AT = issue_time(datetime.now(UTC), CONFIG.forecast.issue_minute)
NEWEST_AT = ISSUED_AT.replace(minute=22)


def source(station: Station, start: datetime, end: datetime) -> list[Observation]:
    """Kupferdreh at 10 cm (55 cm after the offset) every hour at :22."""
    readings = [NEWEST_AT - timedelta(hours=hours) for hours in range(3)]
    return [Observation(station.id, at, 10.0) for at in readings if start <= at < end]


class RisingModel:
    """Predicts the last level plus the lead in cm, or NaN to act as a missing input."""

    name = RIDGE

    def __init__(self, missing: bool = False) -> None:
        self.missing = missing

    def fit(self, train: pd.DataFrame) -> None:
        raise AssertionError("never trained in the live job")

    def predict(self, rows: pd.DataFrame) -> npt.NDArray[np.float64]:
        assert not any(column.startswith("target_") for column in rows.columns)
        leads = np.arange(1, CONFIG.evaluation.leads_hours + 1, dtype=np.float64)
        levels: npt.NDArray[np.float64] = rows[[contract.KD_LAST_CM]].to_numpy() + leads
        return levels * np.nan if self.missing else levels


def rising(band_table: bands.BandTable | None = None, missing: bool = False) -> TrainedModel:
    return TrainedModel(RisingModel(missing), band_table)


def band_table() -> bands.BandTable:
    """A band table whose error scale is 1 cm plus the predicted change."""
    leads = CONFIG.evaluation.leads_hours
    coverages = len(CONFIG.bands.coverages_percent)
    steps = np.linspace(1, 2, coverages)[:, np.newaxis] * np.ones(leads)
    return bands.BandTable(
        coverages_percent=CONFIG.bands.coverages_percent,
        scale_coefficients=np.tile([1.0, 1.0, 0.0], (leads, 1)),
        scale_caps=np.full(leads, 1000.0),
        z_lower=-steps,
        z_upper=steps,
        persistence_lower=-steps,
        persistence_upper=steps,
    )


def test_model_forecast_is_saved_next_to_persistence(conn: Conn) -> None:
    result = run_hourly(source, conn, RIDGE_CONFIG, ISSUED_AT, load_model=rising)
    assert newest_forecast(conn, "kupferdreh", RIDGE) == result
    assert newest_forecast(conn, "kupferdreh", "persistence") is not None
    assert (result.model, result.newest_observation_at) == (RIDGE, NEWEST_AT)
    # One point per lead the model forecasts, nothing beyond.
    assert len(result.points) == CONFIG.evaluation.leads_hours
    # Lead k at floor(t) + k h + 22 min, the training target time.
    assert result.points[0].valid_at == NEWEST_AT + timedelta(hours=1)
    assert result.points[-1].valid_at == NEWEST_AT + timedelta(hours=24)
    assert [point.level_cm for point in result.points[:2]] == [56.0, 57.0]
    # A model file without a band table gives no bands.
    assert result.situation is None
    assert all(point.bands == () for point in result.points)


def seed_icon(conn: Conn) -> None:
    """One ICON-D2 run, known 1 h before the issue time, 0.2 mm every hour."""
    rain = CONFIG.rain
    series = forecast_series(rain.forecast.source, rain.forecast.ring_percentile, "test")
    ensure_series(conn, series)
    run_at = ISSUED_AT.replace(minute=0) - timedelta(hours=3)
    values = [
        InputForecastValue(one.id, run_at, run_at + timedelta(hours=hour), 0.2, run_at)
        for one in series
        for hour in range(1, 60)
    ]
    upsert_input_forecasts(conn, values, run_at)


def test_model_forecast_carries_bands_and_situation(conn: Conn) -> None:
    seed_icon(conn)
    result = run_hourly(
        source, conn, RIDGE_CONFIG, ISSUED_AT, load_model=lambda: rising(band_table())
    )
    assert newest_forecast(conn, "kupferdreh", RIDGE) == result
    # The model rises by up to 24 cm: far above the strong-change threshold.
    assert result.situation == bands.STRONG
    first, last = result.points[0], result.points[-1]
    # Lead 1: change 1 cm, scale 2 cm, 80 % band ±2 cm; the 95 % band ±4 cm.
    assert [(band.coverage_percent, band.lower_cm, band.upper_cm) for band in first.bands] == [
        (80, 54.0, 58.0),
        (90, 53.0, 59.0),
        (95, 52.0, 60.0),
    ]
    # Lead 24: change 24 cm, scale 25 cm.
    assert (last.bands[0].lower_cm, last.bands[0].upper_cm) == (79.0 - 25.0, 79.0 + 25.0)


def test_broken_band_table_keeps_the_forecast_without_bands(
    conn: Conn, caplog: pytest.LogCaptureFixture
) -> None:
    full = band_table()
    # Only 80 % while the config wants 80, 90 and 95 %: a table from another config.
    only_80 = bands.BandTable(
        (80,),
        full.scale_coefficients,
        full.scale_caps,
        *(values[:1] for values in (full.z_lower, full.z_upper)),
        *(values[:1] for values in (full.persistence_lower, full.persistence_upper)),
    )
    with caplog.at_level(logging.ERROR):
        result = run_hourly(
            source, conn, RIDGE_CONFIG, ISSUED_AT, load_model=lambda: rising(only_80)
        )
    assert result.model == RIDGE
    assert result.situation is None
    assert all(point.bands == () for point in result.points)
    assert "bands failed" in caplog.text


def test_unknown_rain_gives_persistence_bands_and_the_degraded_tag(conn: Conn) -> None:
    result = run_hourly(
        source, conn, RIDGE_CONFIG, ISSUED_AT, load_model=lambda: rising(band_table())
    )
    assert result.situation == bands.DEGRADED
    # Persistence errors of ±1 cm at 80 %, widened to the 1.5 cm floor.
    band = result.points[0].bands[0]
    assert (band.lower_cm, band.upper_cm) == (56.0 - 1.5, 56.0 + 1.5)


def raise_on_load() -> TrainedModel:
    raise RuntimeError("bucket gone")


@pytest.mark.parametrize("load_model", [raise_on_load, lambda: rising(missing=True), None], ids=str)
def test_failing_model_keeps_the_persistence_forecast(
    conn: Conn, caplog: pytest.LogCaptureFixture, load_model: object
) -> None:
    with caplog.at_level(logging.ERROR):
        result = run_hourly(source, conn, RIDGE_CONFIG, ISSUED_AT, load_model=load_model)  # type: ignore[arg-type]
    assert result.model == "persistence"
    assert newest_forecast(conn, "kupferdreh", "persistence") == result
    assert newest_forecast(conn, "kupferdreh", RIDGE) is None
    [record] = caplog.records
    assert (record.model, record.issued_at, record.exc_info is not None) == (  # type: ignore[attr-defined]
        RIDGE,
        ISSUED_AT.isoformat(),
        True,
    )


def test_persistence_config_never_loads_a_model(conn: Conn) -> None:
    result = run_hourly(source, conn, CONFIG, ISSUED_AT, load_model=raise_on_load)
    assert result.model == "persistence"
    assert newest_forecast(conn, "kupferdreh", RIDGE) is None


def stored_ridge(name: str = RIDGE) -> dict[str, object]:
    model = CuratedChange(
        CONFIG.evaluation, name=name, inputs=RIDGE_V2, split=True, alpha=RIDGE_V2_ALPHA
    )
    model.coefficients = np.zeros((2, CONFIG.evaluation.leads_hours, len(RIDGE_V2)))
    return {"model": model.to_dict(), "trained": {}}


def test_model_file_loads_the_configured_model() -> None:
    loaded = model_from_file(stored_ridge(), RIDGE_CONFIG)
    assert (loaded.model.name, loaded.bands) == (RIDGE, None)
    with_bands = {**stored_ridge(), "bands": band_table().to_dict()}
    loaded_bands = model_from_file(with_bands, RIDGE_CONFIG).bands
    assert loaded_bands is not None
    np.testing.assert_array_equal(loaded_bands.z_upper, band_table().z_upper)
    with pytest.raises(ValueError, match="config wants"):
        model_from_file(stored_ridge("rain_change:v2:split"), RIDGE_CONFIG)
