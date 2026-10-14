"""The baseline every model must beat: the last cleaned level, for every lead."""

import numpy as np
import numpy.typing as npt
import pandas as pd

from pegel.config import EvaluationSettings
from pegel.evaluation.contract import KD_LAST_CM


class Persistence:
    name = "persistence"

    def __init__(self, settings: EvaluationSettings) -> None:
        self._leads = settings.leads_hours

    def fit(self, train: pd.DataFrame) -> None:
        pass

    def predict(self, rows: pd.DataFrame) -> npt.NDArray[np.float64]:
        last = rows[KD_LAST_CM].to_numpy(dtype=np.float64)
        return np.repeat(last[:, np.newaxis], self._leads, axis=1)
