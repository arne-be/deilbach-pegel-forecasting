"""Model 4 of the ladder (docs/decisions/0008): the last level plus the upstream wave.

    change_k = c_k · Langenberg 3 h change + d_k · Nierenhof 3 h change   (lag 0 minus lag 3)

One set of factors per lead fitted by least squares on the change from the last cleaned level,
`target_k - kd_last_cm`.
- Fit: per lead, only on rows where both inputs and that lead's target exist.
- No intercept: with no recent upstream change, the level should stay where it is. An intercept
  would only learn the mean change of the training period.
- Predict: a row with a missing input gets the persistence forecast (`kd_last_cm`), so the
  model is scored on the same rows as persistence.
"""

import numpy as np
import numpy.typing as npt
import pandas as pd

from pegel.config import EvaluationSettings
from pegel.evaluation import contract

Array = npt.NDArray[np.float64]
CHANGE_HOURS = 3


class Upstream:
    name = "upstream"

    def __init__(self, settings: EvaluationSettings) -> None:
        self._leads = settings.leads_hours
        # Shape (inputs, leads): column k-1 holds the factors of lead k.
        self.coefficients: Array = np.empty((0, self._leads))

    def inputs(self, rows: pd.DataFrame) -> Array:
        """Shape (len(rows), 2); NaN where a level is missing."""
        changes = [
            rows[f"{prefix}_lag_0"] - rows[f"{prefix}_lag_{CHANGE_HOURS}"]
            for prefix in (
                contract.GAUGE_PREFIXES["langenberg"],
                contract.GAUGE_PREFIXES["nierenhof"],
            )
        ]
        return np.column_stack(changes).astype(np.float64)

    def fit(self, train: pd.DataFrame) -> None:
        inputs = self.inputs(train)
        targets = train[contract.lead_columns(contract.TARGET, self._leads)].to_numpy(np.float64)
        change = targets - _last_level(train)
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
        prediction: Array = _last_level(rows) + change
        return prediction


def _last_level(rows: pd.DataFrame) -> Array:
    return rows[[contract.KD_LAST_CM]].to_numpy(np.float64)
