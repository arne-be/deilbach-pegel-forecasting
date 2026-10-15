"""The hourly run with a trained model next to persistence, and the model file."""

import logging
from datetime import UTC, datetime, timedelta

import numpy as np
import numpy.typing as npt
import pandas as pd
import psycopg
import pytest
from psycopg.rows import TupleRow

from pegel.adapters.model_files import model_from_file
from pegel.adapters.storage.forecasts import newest_forecast
from pegel.config import Station, load_config
from pegel.core.observations import Observation
from pegel.core.schedule import issue_time
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


def test_model_forecast_is_saved_next_to_persistence(conn: Conn) -> None:
    result = run_hourly(source, conn, RIDGE_CONFIG, ISSUED_AT, load_model=RisingModel)
    assert newest_forecast(conn, "kupferdreh", RIDGE) == result
    assert newest_forecast(conn, "kupferdreh", "persistence") is not None
    assert (result.model, result.newest_observation_at) == (RIDGE, NEWEST_AT)
    assert len(result.points) == CONFIG.forecast.horizon_hours
    # Lead k at floor(t) + k h + 22 min, the training target time.
    assert result.points[0].valid_at == NEWEST_AT + timedelta(hours=1)
    assert result.points[-1].valid_at == NEWEST_AT + timedelta(hours=48)
    assert [point.level_cm for point in result.points[:2]] == [56.0, 57.0]
    # After the model's last lead the level holds.
    assert {point.level_cm for point in result.points[23:]} == {79.0}


def raise_on_load() -> RisingModel:
    raise RuntimeError("bucket gone")


@pytest.mark.parametrize(
    "load_model", [raise_on_load, lambda: RisingModel(missing=True), None], ids=str
)
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
    assert model_from_file(stored_ridge(), RIDGE_CONFIG).name == RIDGE
    with pytest.raises(ValueError, match="config wants"):
        model_from_file(stored_ridge("rain_change:v2:split"), RIDGE_CONFIG)
