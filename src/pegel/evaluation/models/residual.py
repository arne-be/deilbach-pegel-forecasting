"""LightGBM on the residual of `ridge:change:v2`, one booster per lead.

Ridge carries the flood size, because it is linear and extrapolates. The trees add what a
linear model can't express, such as rain times level, or season. A tree can't go past the
residuals it trained on, so that cap limits only the correction, not the forecast.

The trees learn out-of-fold residuals: the training rows are cut into time blocks, and each
block's residual comes from ridge fitted on the other blocks. In-sample ridge residuals were
8 to 30 % smaller than out-of-fold ones on the inner splits, so trees fitted on them would
learn too small a correction. The final ridge is fitted on all training rows. Explained in
docs/models.md.
"""

from typing import Any

import lightgbm as lgb
import numpy as np
import numpy.typing as npt
import pandas as pd

from pegel.config import EvaluationSettings
from pegel.evaluation import contract
from pegel.evaluation.models.curated import (
    INPUTS,
    RIDGE_V2,
    RIDGE_V2_ALPHA,
    CuratedChange,
    InputFunction,
    _row_input,
    zone_cell_counts,
)

Array = npt.NDArray[np.float64]

RESIDUAL_BLOCKS = 3
SEED = 42
# Rounds and min_data_in_leaf chosen on inner time splits of the training rows (docs/models.md):
# more rounds made the inner validation worse for both variants.
ROUNDS = 10
PARAMETERS: dict[str, Any] = {
    "objective": "regression",
    "learning_rate": 0.05,
    "num_leaves": 15,
    "max_depth": 4,
    "min_data_in_leaf": 200,
    "lambda_l2": 10.0,
    "linear_lambda": 10.0,
    "feature_fraction": 0.8,
    "seed": SEED,
    "deterministic": True,
    "num_threads": 4,
    "verbosity": -1,
}


def _angle(rows: pd.DataFrame, period: str) -> Array:
    issued_at = rows[contract.ISSUED_AT]
    if period == "day":
        fraction = (issued_at.dt.hour + issued_at.dt.minute / 60) / 24
    else:
        fraction = issued_at.dt.dayofyear / 365.25
    angle: Array = 2 * np.pi * fraction.to_numpy(np.float64)
    return angle


TREE_INPUTS: dict[str, InputFunction] = {
    **{name: INPUTS[name] for name in RIDGE_V2 if name != "constant"},
    "last_level": _row_input(lambda rows: rows[contract.KD_LAST_CM].to_numpy(np.float64)),
    "hour_sin": _row_input(lambda rows: np.sin(_angle(rows, "day"))),
    "hour_cos": _row_input(lambda rows: np.cos(_angle(rows, "day"))),
    "season_sin": _row_input(lambda rows: np.sin(_angle(rows, "year"))),
    "season_cos": _row_input(lambda rows: np.cos(_angle(rows, "year"))),
}


def ridge_v2(settings: EvaluationSettings) -> CuratedChange:
    return CuratedChange(
        settings, name="ridge:change:v2", inputs=RIDGE_V2, split=True, alpha=RIDGE_V2_ALPHA
    )


class ResidualTrees:
    def __init__(
        self,
        settings: EvaluationSettings,
        *,
        name: str,
        linear_tree: bool = False,
    ) -> None:
        self.name = name
        self._settings = settings
        self._leads = settings.leads_hours
        self._parameters = {**PARAMETERS, "linear_tree": linear_tree}
        self._cell_counts = zone_cell_counts()
        self.ridge = ridge_v2(settings)
        self.boosters: list[lgb.Booster] = []

    def tree_inputs(self, rows: pd.DataFrame) -> Array:
        """Shape (rows, leads, inputs), in the order of TREE_INPUTS."""
        columns = [build(rows, self._leads, self._cell_counts) for build in TREE_INPUTS.values()]
        return np.stack(columns, axis=2)

    def out_of_fold_residuals(self, train: pd.DataFrame) -> Array:
        """Target minus ridge, each time block predicted by ridge fitted on the other blocks."""
        order = np.argsort(train[contract.ISSUED_AT].to_numpy(), kind="stable")
        targets = _targets(train, self._leads)
        residuals: Array = np.full(targets.shape, np.nan)
        for block in np.array_split(order, RESIDUAL_BLOCKS):
            inside = np.zeros(len(train), dtype=bool)
            inside[block] = True
            ridge = ridge_v2(self._settings)
            ridge.fit(train[~inside])
            residuals[inside] = targets[inside] - ridge.predict(train[inside])
        return residuals

    def fit(self, train: pd.DataFrame) -> None:
        residuals = self.out_of_fold_residuals(train)
        self.ridge.fit(train)
        inputs = self.tree_inputs(train)
        self.boosters = []
        for lead in range(self._leads):
            known = np.isfinite(residuals[:, lead])
            data = lgb.Dataset(
                inputs[known, lead],
                residuals[known, lead],
                feature_name=list(TREE_INPUTS),
                params={"verbosity": -1},
            )
            self.boosters.append(lgb.train(self._parameters, data, num_boost_round=ROUNDS))

    def correction(self, rows: pd.DataFrame) -> Array:
        """Shape (rows, leads): what the trees add to ridge."""
        inputs = self.tree_inputs(rows)
        columns = [booster.predict(inputs[:, lead]) for lead, booster in enumerate(self.boosters)]
        return np.column_stack(columns).astype(np.float64)

    def predict(self, rows: pd.DataFrame) -> Array:
        prediction: Array = self.ridge.predict(rows) + self.correction(rows)
        return prediction


def _targets(rows: pd.DataFrame, leads: int) -> Array:
    return rows[contract.lead_columns(contract.TARGET, leads)].to_numpy(np.float64)
