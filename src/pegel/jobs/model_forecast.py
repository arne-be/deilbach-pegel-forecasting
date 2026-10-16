"""The forecast of a trained model (`forecast.model`), from the same input row as training,
with its uncertainty bands."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta

import numpy as np
import numpy.typing as npt
import pandas as pd

from pegel.adapters.model_files import TrainedModel
from pegel.config import PegelConfig
from pegel.core import bands, features
from pegel.core.forecasts import Band, Forecast, ForecastPoint
from pegel.core.issue_inputs import TARGET_MINUTE
from pegel.evaluation import contract
from pegel.jobs import eval_set

# Loads the trained model, e.g. from S3. Passed in, so tests need no S3.
ModelLoader = Callable[[], TrainedModel]


def model_forecast(
    conn: eval_set.Conn, config: PegelConfig, issued_at: datetime, trained: TrainedModel
) -> Forecast:
    """Builds the input row for the issue time and predicts with the model; bands too when the
    model file has a band table."""
    model = trained.model
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
    points = model_points(issued_at, levels)
    situation = None
    if trained.bands is not None:
        row_levels = levels[np.newaxis, :]
        last_level = inputs[contract.KD_LAST_CM].to_numpy(np.float64)
        icon_to_lead = features.icon_cumulative(inputs, leads)
        bounds = bands.band_bounds(
            trained.bands, row_levels, last_level, icon_to_lead, config.bands
        )
        [situation] = bands.situations(row_levels, last_level, icon_to_lead, config.bands)
        points = with_bands(points, bounds)
    return Forecast(
        station_id=config.forecast.station_id,
        model=model.name,
        issued_at=issued_at,
        newest_observation_at=newest_observation_at.to_pydatetime(),
        points=points,
        situation=situation,
    )


def with_bands(
    points: tuple[ForecastPoint, ...],
    bounds: dict[int, tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]],
) -> tuple[ForecastPoint, ...]:
    """The points with one band per coverage, narrowest first; `bounds` are (1, leads)."""
    return tuple(
        replace(
            point,
            bands=tuple(
                Band(coverage, float(lower[0, lead]), float(upper[0, lead]))
                for coverage, (lower, upper) in sorted(bounds.items())
            ),
        )
        for lead, point in enumerate(points)
    )


def model_points(issued_at: datetime, levels: npt.NDArray[np.float64]) -> tuple[ForecastPoint, ...]:
    """Lead k at floor(t) + k h + 22 min, one point per lead the model forecasts.

    The model was trained on the reading at exactly that time (issue_inputs.targets_by_lead).
    With the usual hh:22 newest reading it is also where persistence puts lead k (newest
    reading + k h), so both forecasts land on the same future readings.
    """
    first_hour = issued_at.replace(minute=0, second=0, microsecond=0)
    offset = TARGET_MINUTE.to_pytimedelta()
    return tuple(
        ForecastPoint(first_hour + timedelta(hours=lead) + offset, float(level))
        for lead, level in enumerate(levels, start=1)
    )
