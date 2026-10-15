"""The forecast of a trained model (`forecast.model`), from the same input row as training."""

from collections.abc import Callable
from datetime import datetime, timedelta

import numpy as np
import numpy.typing as npt
import pandas as pd

from pegel.config import PegelConfig
from pegel.core.forecasts import Forecast, ForecastPoint
from pegel.core.issue_inputs import TARGET_MINUTE
from pegel.evaluation import contract
from pegel.jobs import eval_set

# Loads the trained model, e.g. from S3. Passed in, so tests need no S3.
ModelLoader = Callable[[], contract.Model]


def model_forecast(
    conn: eval_set.Conn, config: PegelConfig, issued_at: datetime, model: contract.Model
) -> Forecast:
    """Builds the input row for the issue time and predicts with the model."""
    rows, _ = eval_set.build_rows(conn, config, pd.DatetimeIndex([issued_at]))
    # Targets lie in the future, so they are NaN here; models never see them (as in the harness).
    inputs = rows.loc[:, ~rows.columns.str.startswith(f"{contract.TARGET}_")]
    newest_observation_at = inputs[contract.KD_LAST_AT].iloc[0]
    if pd.isna(newest_observation_at):
        raise ValueError(f"no cleaned level known at {issued_at.isoformat()}")
    levels = model.predict(inputs)[0]
    leads = config.evaluation.leads_hours
    if levels.shape != (leads,) or not np.isfinite(levels).all():
        raise ValueError(f"{model.name} predicted {levels}, expected {leads} finite levels")
    return Forecast(
        station_id=config.forecast.station_id,
        model=model.name,
        issued_at=issued_at,
        newest_observation_at=newest_observation_at.to_pydatetime(),
        points=model_points(issued_at, levels, config.forecast.horizon_hours),
    )


def model_points(
    issued_at: datetime, levels: npt.NDArray[np.float64], horizon_hours: int
) -> tuple[ForecastPoint, ...]:
    """Lead k at floor(t) + k h + 22 min; leads past the model's last hold its last value.

    The model was trained on the reading at exactly that time (issue_inputs.targets_by_lead).
    With the usual hh:22 newest reading it is also where persistence puts lead k (newest
    reading + k h), so both forecasts land on the same future readings.
    """
    first_hour = issued_at.replace(minute=0, second=0, microsecond=0)
    offset = TARGET_MINUTE.to_pytimedelta()
    return tuple(
        ForecastPoint(
            first_hour + timedelta(hours=lead) + offset, float(levels[min(lead, len(levels)) - 1])
        )
        for lead in range(1, horizon_hours + 1)
    )
