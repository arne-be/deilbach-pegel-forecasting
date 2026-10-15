"""Stress test: train a model only on issue times that stay below a cap.

A training row is dropped when the cleaned level at the issue time or any target is above the
cap, so the model never learns from an issue time with a level or target above it. Test rows
are never filtered. Never a live candidate; see docs/models.md.
"""

import numpy as np
import numpy.typing as npt
import pandas as pd

from pegel.config import EvaluationSettings
from pegel.evaluation import contract
from pegel.evaluation.harness import ModelFactory


def rows_below_cap(train: pd.DataFrame, leads: int, cap_cm: float) -> pd.DataFrame:
    """The rows whose last level and targets are all at or below the cap; NaN counts as below."""
    columns = [contract.KD_LAST_CM, *contract.lead_columns(contract.TARGET, leads)]
    above = (train[columns].to_numpy(np.float64) > cap_cm).any(axis=1)
    return train[~above]


class CappedTraining:
    def __init__(self, model: contract.Model, leads: int, cap_cm: float) -> None:
        self.name = f"{model.name}:cap{cap_cm:g}"
        self._model = model
        self._leads = leads
        self._cap_cm = cap_cm

    def fit(self, train: pd.DataFrame) -> None:
        self._model.fit(rows_below_cap(train, self._leads, self._cap_cm))

    def predict(self, rows: pd.DataFrame) -> npt.NDArray[np.float64]:
        return self._model.predict(rows)


def capped(factory: ModelFactory, cap_cm: float) -> ModelFactory:
    def build(settings: EvaluationSettings) -> contract.Model:
        return CappedTraining(factory(settings), settings.leads_hours, cap_cm)

    return build
