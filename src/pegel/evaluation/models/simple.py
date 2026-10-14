"""Models 2 to 4 of the ladder (docs/decisions/0008): the last level plus a linear change.

Each model forecasts the change from the last cleaned level, `target_k - kd_last_cm`, as a
linear function of a few inputs, with one set of factors per lead fitted by least squares.
- Fit: per lead, only on rows where every input and that lead's target exist.
- No intercept: with no distance to the base level and no recent change, the level should stay
  where it is. An intercept would only learn the mean change of the training period.
- Predict: a row with a missing input gets the persistence forecast (`kd_last_cm`), so every
  model is scored on the same rows as persistence.
"""

import numpy as np
import numpy.typing as npt
import pandas as pd

from pegel.config import EvaluationSettings
from pegel.core.features import features
from pegel.evaluation import contract
from pegel.evaluation.targets import from_target, to_target

Array = npt.NDArray[np.float64]
CHANGE_HOURS = 3


class _LinearChange:
    """The shared fit and predict; a subclass names itself and builds its inputs."""

    name: str

    def __init__(self, settings: EvaluationSettings) -> None:
        self._leads = settings.leads_hours
        # Shape (inputs, leads): column k-1 holds the factors of lead k.
        self.coefficients: Array = np.empty((0, self._leads))

    def inputs(self, rows: pd.DataFrame) -> Array:
        """Shape (len(rows), inputs); NaN where an input is missing."""
        raise NotImplementedError

    def fit(self, train: pd.DataFrame) -> None:
        inputs = self.inputs(train)
        change = to_target(train, "change")
        complete = np.isfinite(inputs).all(axis=1)
        factors = []
        for lead in range(self._leads):
            usable = complete & np.isfinite(change[:, lead])
            if not usable.any():
                raise ValueError(f"{self.name}: no training rows with inputs for lead {lead + 1}")
            solution, *_ = np.linalg.lstsq(inputs[usable], change[usable, lead], rcond=None)
            factors.append(solution)
        self.coefficients = np.column_stack(factors)

    def predict(self, rows: pd.DataFrame) -> Array:
        inputs = self.inputs(rows)
        change = inputs @ self.coefficients
        change[~np.isfinite(inputs).all(axis=1)] = 0.0
        return from_target(change, rows, "change")


class Recession(_LinearChange):
    """`base + a_k * (last - base)`, base the 30-day median; coefficients hold `a_k - 1`."""

    name = "recession"

    def inputs(self, rows: pd.DataFrame) -> Array:
        distance = rows[contract.KD_LAST_CM] - rows[contract.KD_BASE_30D_CM]
        return distance.to_numpy(dtype=np.float64)[:, np.newaxis]


class DampedTrend(_LinearChange):
    """`last + b_k * change_3h`, see `kupferdreh_change_3h`."""

    name = "damped_trend"

    def inputs(self, rows: pd.DataFrame) -> Array:
        return kupferdreh_change_3h(rows)[:, np.newaxis]


class Upstream(_LinearChange):
    """`last + c_k * Langenberg change_3h + d_k * Nierenhof change_3h`, lag 0 minus lag 3."""

    name = "upstream"

    def inputs(self, rows: pd.DataFrame) -> Array:
        upstream = features(rows, with_icon=False)[["lb_change_3h", "nh_change_3h"]]
        return upstream.to_numpy(dtype=np.float64)


def kupferdreh_change_3h(rows: pd.DataFrame) -> Array:
    """The last level minus the hourly lag 3 hours older than the lag the last level falls in.

    Lag 0 is missing at about 4 in 10 issue times, since the reading of the hour often arrives
    after :30, so `kd_lag_0 - kd_lag_3` would lose them. Lag k covers ages in [k h, (k+1) h),
    so a last level 40 minutes old pairs with lag 3 and one 70 minutes old with lag 4. NaN when
    that lag is missing or beyond the window.
    """
    age = rows[contract.ISSUED_AT] - rows[contract.KD_LAST_AT]
    lag = np.floor(age.dt.total_seconds().to_numpy(dtype=np.float64) / 3600) + CHANGE_HOURS
    lags = rows[contract.level_lag_columns("kupferdreh")].to_numpy(dtype=np.float64)
    inside = lag < contract.LEVEL_LAG_HOURS
    earlier: Array = np.full(len(rows), np.nan)
    positions = np.flatnonzero(inside)
    earlier[positions] = lags[positions, lag[inside].astype(int)]
    return rows[contract.KD_LAST_CM].to_numpy(dtype=np.float64) - earlier
