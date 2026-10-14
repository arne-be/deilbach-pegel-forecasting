"""Model 5: a linear model per lead (ridge) on the shared features (docs/decisions/0008).

Gaps are filled in the model, never in the dataset: a missing level lag takes the next newer
known level of the same gauge, everything else the median of the training rows. Each feature
group that had gaps in training gets one flag column, so the model can tell a filled value.

The error of the lead-1 forecast issued one hour earlier is not a feature yet: it needs the
model's own previous forecast.
"""

import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.linear_model import Ridge as SklearnRidge
from sklearn.preprocessing import StandardScaler

from pegel.config import EvaluationSettings
from pegel.core.features import UPSTREAM_LAG_HOURS, features
from pegel.evaluation import contract, targets

# Strengths on standardised features. The 25 near-identical Kupferdreh level columns and a
# short first training window (under a year, so time of year extrapolates) want strong
# shrinkage; how strong is chosen per fold on the newest training rows, never on the test.
ALPHAS = (1.0, 10.0, 100.0, 1000.0, 10000.0)
VALIDATION_FRACTION = 0.2

# Newest first: a missing value takes the one to its left.
_LEVEL_WINDOWS = (
    [contract.KD_LAST_CM, *contract.level_lag_columns("kupferdreh")],
    contract.lag_columns(contract.GAUGE_PREFIXES["langenberg"], UPSTREAM_LAG_HOURS),
    contract.lag_columns(contract.GAUGE_PREFIXES["nierenhof"], UPSTREAM_LAG_HOURS),
)


def feature_group(column: str) -> str:
    """`kd`, `lb`, `nh`, `radar`, `icon` or `year`: the source a feature comes from."""
    return column.split("_", 1)[0]


def fill_from_newer(frame: pd.DataFrame) -> pd.DataFrame:
    """Fills each missing level lag from the next newer known level of the same gauge."""
    filled = frame.copy()
    for window in _LEVEL_WINDOWS:
        filled[window] = filled[window].ffill(axis=1)
    return filled


class Imputer:
    """Fill values and flag columns, learned from training rows only."""

    def fit(self, frame: pd.DataFrame) -> None:
        self.columns = list(frame.columns)
        missing = frame.isna()
        self.flagged_groups = sorted({feature_group(c) for c in self.columns if missing[c].any()})
        # A column with no value in training carries no information; 0 keeps it inert.
        self.medians = fill_from_newer(frame).median().fillna(0.0)

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame[self.columns]
        missing = frame.isna()
        groups = missing.T.groupby(feature_group).any().T
        flags = {f"{group}_missing": groups[group].astype(float) for group in self.flagged_groups}
        filled = fill_from_newer(frame).fillna(self.medians)
        return pd.concat([filled, pd.DataFrame(flags, index=frame.index)], axis=1)


class Ridge:
    """One ridge regression per lead on the level or the change from the last level."""

    def __init__(
        self,
        settings: EvaluationSettings,
        *,
        kind: targets.TargetKind = "level",
        with_icon: bool = True,
    ) -> None:
        if kind == "step":
            raise ValueError("ridge can't use the lead feature the step target needs")
        self.name = f"ridge:{kind}" + ("" if with_icon else ":no_icon")
        self._leads = settings.leads_hours
        self._kind: targets.TargetKind = kind
        self._with_icon = with_icon
        self._imputer = Imputer()
        self._scaler = StandardScaler()
        self._models: list[SklearnRidge] = []

    def fit(self, train: pd.DataFrame) -> None:
        early, late = self._split_by_time(train)
        self.alpha = min(ALPHAS, key=lambda alpha: self._validation_error(early, late, alpha))
        self._fit(train, self.alpha)

    def predict(self, rows: pd.DataFrame) -> npt.NDArray[np.float64]:
        return targets.from_target(self._predict_target(rows), rows, self._kind)

    def _split_by_time(self, train: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """The newest rows for validation; an embargo of the longest lead keeps their targets
        out of the earlier rows, as between training and test."""
        issued_at = train[contract.ISSUED_AT]
        cut = issued_at.sort_values().iloc[int(len(train) * (1 - VALIDATION_FRACTION))]
        embargo = pd.Timedelta(hours=self._leads)
        return train[issued_at < cut - embargo], train[issued_at >= cut]

    def _validation_error(self, early: pd.DataFrame, late: pd.DataFrame, alpha: float) -> float:
        self._fit(early, alpha)
        errors = self._predict_target(late) - targets.to_target(late, self._kind, self._leads)
        return float(np.nanmean(np.abs(errors)))

    def _fit(self, train: pd.DataFrame, alpha: float) -> None:
        frame = features(train, with_icon=self._with_icon)
        self._imputer.fit(frame)
        inputs = self._scaler.fit_transform(self._imputer.transform(frame))
        target = targets.to_target(train, self._kind, self._leads)
        self._models = []
        for lead in range(self._leads):
            known = ~np.isnan(target[:, lead])
            # Ridge's default solvers are deterministic, so there is nothing to seed.
            model = SklearnRidge(alpha=alpha)
            model.fit(inputs[known], target[known, lead])
            self._models.append(model)

    def _predict_target(self, rows: pd.DataFrame) -> npt.NDArray[np.float64]:
        frame = features(rows, with_icon=self._with_icon)
        inputs = self._scaler.transform(self._imputer.transform(frame))
        return np.column_stack([model.predict(inputs) for model in self._models]).astype(np.float64)
